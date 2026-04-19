# ai-maestro-janitor

<!--BADGES-START-->
<!--BADGES-END-->

Session-scoped janitor plugin for Claude Code. Reconciles drift between what
the repo actually contains and what the todo list / open PRs / worktrees /
TRDDs claim, and handles rate-limit auto-resume plus prompt-cache keep-alive —
all through a single durable `CronCreate` heartbeat and hooks. No external
daemons, no Monitors.

## How it works

One durable recurring cron is armed on session start via the `/janitor-arm`
skill. Each cron fire is a fresh user turn that runs `scripts/dispatch.sh`:

1. If the `rate-limited.flag` is set (meaning a prior `StopFailure` captured a
   rate-limit window), dispatch emits `[janitor-resume]` and clears the flag.
   Claude picks it up as a cue to resume the previous pending task. The cron
   fire itself proves the API is reachable again, because it delivered.
2. Otherwise dispatch invokes each due detector in sequence. Each detector has
   a configurable minimum internal cadence that dispatch guards via
   `.janitor/state/last-run-<detector>.ts` files — the heartbeat may fire
   every 4 minutes, but `trdd-drift` still only runs once an hour.
3. Each detector emits drift lines (deduped via per-detector `*-seen.txt`
   files) to stdout. Dispatch passes them through to the cron prompt, where
   Claude surfaces them to the user.

The heartbeat also keeps the Anthropic prompt cache warm — every fire inside
the 5-minute cache TTL refreshes it — and catches rate-limit recovery without
a dedicated retry loop, because queued fires deliver in batch as soon as the
window clears.

## Detectors

| Detector | Internal cadence | What it surfaces |
| --- | --- | --- |
| `pr-reconciler` | 15 min | Open PRs whose HEAD is already on main (no-op candidates); PRs idle >14 days. |
| `worktree-janitor` | 15 min | Worktrees whose branch no longer exists or is already merged into main. |
| `trdd-drift` | 1 h | TRDDs marked `In progress` that have not been touched in >14 days. |
| `trdd-reminder` | 4 h | Consolidated reminder of all TRDDs currently `In progress`. |
| `task-pr-mismatch` | 30 min | Session tasks whose status contradicts the state of a referenced PR. |

The heartbeat cron runs every 4 minutes by default (`*/4 * * * *`), so the
detectors fire at roughly their configured cadence without any additional
bookkeeping.

## Hooks

- `SessionStart` initializes `.janitor/state/`, refreshes the idle timer, and
  prints a one-line context reminder to run `/janitor-arm`.
- `UserPromptSubmit` refreshes the idle timer.
- `Stop` refreshes the idle timer after a successful turn.
- `StopFailure` writes `rate-limited.flag`; the next heartbeat fire picks it
  up and emits `[janitor-resume]`.

## Skills

- `/janitor-arm` — arms the heartbeat cron. Idempotent: replaces any existing
  `[janitor-heartbeat]` job. Run this once per session (or after a 7-day
  auto-expiry).
- `/janitor-audit` — on-demand aggregate scan. Runs every detector
  synchronously and prints a consolidated markdown report with proposed
  remediation commands (never executed automatically).

## Install

This plugin is designed for **project scope only** — install it in the
projects where you want the janitor running, not globally.

```bash
claude plugin marketplace add Emasoft/ai-maestro-plugins
claude plugin install ai-maestro-janitor@ai-maestro-plugins --scope project
```

Add `.janitor/` to the project's `.gitignore` so the state/logs directory
never gets committed:

```bash
echo '.janitor/' >> .gitignore
```

Then inside the session, run:

```
/janitor-arm
```

This arms the durable heartbeat. Because `durable: true` is set, the cron
survives session restarts — you do not need to re-arm on each launch unless
the 7-day recurring-cron expiry has hit.

## Data layout

All state and logs live at `$CLAUDE_PROJECT_DIR/.janitor/`:

```text
<project-root>/.janitor/
├── state/
│   ├── rate-limited.flag                 # set by StopFailure, cleared by dispatch on recovery
│   ├── rate-limited-since.ts             # unix ts of rate-limit start
│   ├── last-activity.ts                  # unix ts of last user/claude activity
│   ├── last-run-<detector>.ts            # one per detector, guards internal cadence
│   ├── pr-reconciler-seen.txt            # dedupe key per (PR, SHA)
│   ├── worktree-janitor-seen.txt         # dedupe key per (path, branch)
│   ├── trdd-drift-seen.txt               # dedupe key per (uuid, staleness-bucket)
│   ├── trdd-reminder-session-<hash>.txt  # dedupe key per session+tick
│   └── task-pr-mismatch-seen.txt         # dedupe key per (task, pr, state-transition)
└── logs/
    ├── dispatch.log
    ├── pr-reconciler.log
    ├── worktree-janitor.log
    ├── trdd-drift.log
    ├── trdd-reminder.log
    ├── task-pr-mismatch.log
    ├── session-start.log
    └── stop-failure.log
```

Each project has its own drift registry. Running the plugin in project A
doesn't affect dedupe state in project B.

## Configuration

All knobs are `userConfig` entries in `plugin.json`. Set them at install time
via the `/plugin configure` interface or edit the project's
`.claude/settings.json` directly.

| Key | Default | Meaning |
| --- | --- | --- |
| `github_repo` | derived from `origin` remote | Repo slug for `gh pr list`. |
| `trdd_path` | `design/tasks/` | Relative path to the TRDD directory. |
| `heartbeat_cron` | `*/4 * * * *` | Cron expression for the heartbeat. |
| `pr_reconciler_interval` | 900 | Min seconds between PR reconciliation passes. |
| `worktree_janitor_interval` | 900 | Min seconds between worktree scans. |
| `trdd_drift_interval` | 3600 | Min seconds between TRDD drift checks. |
| `trdd_reminder_interval` | 14400 | Min seconds between in-progress TRDD reminders. |
| `task_pr_mismatch_interval` | 1800 | Min seconds between task/PR cross-checks. |
| `trdd_staleness_days` | 14 | Days a TRDD can sit `In progress` before drift. |
| `stale_pr_days` | 14 | Days an open PR can sit idle before flagged stale. |

## Weekly fallback

The heartbeat only fires while a Claude Code session is open. For coverage
during week-long gaps, this plugin ships a GitHub Actions workflow at
`.github/workflows/weekly-audit.yml` that runs the same drift checks every
Monday at 09:00 UTC and opens a GitHub issue if anything is found.

## Prerequisites

- Claude Code v2.1.98 or later (`CronCreate` / `CronDelete` / `CronList`).
- `gh` CLI authenticated (`gh auth login`).
- `jq` on `$PATH` (standard on macOS, `apt install jq` on Debian/Ubuntu).
- A git repo with an `origin` remote pointing at GitHub.

## Troubleshooting

- **No drift lines surfaced after install**: did you run `/janitor-arm`? The
  heartbeat is not armed automatically — the SessionStart hook prints a
  reminder, but you (or Claude responding to the reminder) must run the skill.
- **Heartbeat stopped firing after 7 days**: recurring crons auto-expire. Run
  `/janitor-arm` again — it replaces any stale heartbeat in `CronList`.
- **`pr-reconciler` silent**: inspect
  `$CLAUDE_PROJECT_DIR/.janitor/logs/pr-reconciler.log`. Most common cause is
  `gh` auth expired — `gh auth status` to check.
- **Duplicate fires**: the dedupe seen-files are per-key. If you want to
  force a re-emit, delete the matching line from
  `$CLAUDE_PROJECT_DIR/.janitor/state/<detector>-seen.txt`.
- **Token cost feels high**: raise `heartbeat_cron` to `*/10 * * * *` or
  longer. Accept that cache-keepalive becomes best-effort past the 5-min TTL.

## License

MIT. See [LICENSE](./LICENSE).
