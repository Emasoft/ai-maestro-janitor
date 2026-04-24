# ai-maestro-janitor

<p align="center">
  <img src="assets/logo.jpg" alt="ai-maestro-janitor" width="600">
</p>

<!--BADGES-START-->
<!--BADGES-END-->

Session-scoped janitor plugin for Claude Code. Reconciles drift between what
the repo actually contains and what the todo list / open PRs / worktrees /
TRDDs claim, and handles rate-limit auto-resume plus prompt-cache keep-alive —
all through a single durable `CronCreate` heartbeat and hooks. No external
daemons, no monitors.

**Platform:** macOS and Linux. Bash, `gh`, `jq`, and POSIX `stat`/`date` are
required. Windows is not supported natively; use WSL2.

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
   every 5 minutes, but `trdd-drift` still only runs once an hour.
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
| `worktree-janitor` | 15 min | Worktrees whose branch no longer exists or is already merged into main — emits the exact `git worktree remove` command to run. |
| `trdd-drift` | 1 h | TRDDs marked `In progress` that have not been touched in >14 days. |
| `trdd-reminder` | 4 h | Consolidated reminder of all TRDDs currently `In progress`. |
| `task-pr-mismatch` | 30 min | Session tasks whose status contradicts the state of a referenced PR. |
| `stale-task` | 30 min | Tasks stuck `in_progress` >2h or `pending` >24h with no TaskUpdate. Nudges to resume, close, or defer. |
| `dirty-tree` | 5 min | Working tree left uncommitted for >30 min. Reminds to commit often (every commit is a recovery point) and lists safe alternatives when a git safety guard blocks a destructive op: move files to `_dev/`, use `git rm`, `git stash`, or a backup branch. |
| `subagent-report` | 1 h | Recent `.md` reports in `docs_dev/`, `tests/scenarios/reports/`, `scripts_dev/` that have not been referenced in any commit — catches "subagent wrote a findings file that nobody acted on". |

The heartbeat cron runs every 5 minutes by default (`*/5 * * * *`), so the
detectors fire at roughly their configured cadence without any additional
bookkeeping. The heartbeat prompt is intentionally minimal (~20 tokens of
user text) to keep per-fire overhead low.

## Hooks

- `SessionStart` initializes `.janitor/state/`, refreshes the idle timer, and
  prints a one-line context reminder to run `/janitor-arm`.
- `UserPromptSubmit` refreshes the idle timer.
- `Stop` refreshes the idle timer after a successful turn.
- `StopFailure` writes `rate-limited.flag`; the next heartbeat fire picks it
  up and emits `[janitor-resume]`.

## Skills

- `/janitor-arm` — arms (or renews) the heartbeat cron. Idempotent: replaces
  any existing `[janitor-heartbeat]` job. Run once per session to start, and
  whenever Claude surfaces a `[janitor-renew]` nudge — the skill also writes
  the arm-timestamp that feeds the auto-renewal check.
- `/janitor-disarm` — stops the heartbeat cron. Deletes every
  `[janitor-heartbeat]` job, clears the arm-timestamp, and suppresses the
  renewal nudge. Use to pause janitor activity without uninstalling.
- `/janitor-audit` — on-demand aggregate scan. Runs every detector
  synchronously and prints a consolidated markdown report with proposed
  remediation commands (never executed automatically).

### Auto-renewal of the 7-day cron

Durable recurring `CronCreate` jobs auto-expire after 7 days. dispatch.sh
tracks the arm time in `.janitor/state/heartbeat-armed-at.ts`, and once the
cron is 6+ days old emits a single `[janitor-renew]` line per day. Claude
reads the line, runs `/janitor-arm` (which is idempotent), and the cron is
refreshed back to a fresh 7-day window before the old one dies. The nudge
threshold is tunable via `heartbeat_renewal_threshold_days`.

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

All state files are created at runtime on the first heartbeat fire; none of
them are tracked in git.

```text
<project-root>/.janitor/
├── state/
│   ├── rate-limited.flag                 # set by StopFailure, cleared by dispatch on recovery (runtime)
│   ├── rate-limited-since.ts             # unix ts of rate-limit start (runtime)
│   ├── last-activity.ts                  # unix ts of last user/claude activity
│   ├── last-run-<detector>.ts            # one per detector, guards internal cadence
│   ├── dirty-tree-since.ts               # unix ts the tree first went dirty
│   └── <detector>-seen.txt               # one per detector, dedupe key log
│       # plus: trdd-reminder-session-<hash>.txt (dedupe key per session+day)
└── logs/
    └── <detector>.log                    # one per detector, plus dispatch.log,
                                          # session-start.log, stop-failure.log
```

Each project has its own drift registry. Running the plugin in project A
doesn't affect dedupe state in project B. The detector set is discovered by
iterating `scripts/detectors/`, so `<detector>` above expands to all eight
scripts currently shipped (and automatically covers any new ones added in
future releases).

## Verified behaviour

End-to-end rate-limit recovery was validated on 2026-04-19 against a live
network outage (WiFi off for ~90 seconds, then back on):

1. In-flight turn failed during the outage → `StopFailure` hook wrote
   `.janitor/state/rate-limited.flag` and `rate-limited-since.ts`.
2. The durable heartbeat cron kept ticking inside Claude Code; the fires that
   landed during the outage were enqueued.
3. When the network came back, the next queued fire delivered. `dispatch.sh`
   saw the flag, emitted
   `[janitor-resume] rate-limit cleared after 89s — API is reachable again.`,
   and cleared the flag.
4. Claude Code processed that line as a fresh user turn and resumed the
   previous pending task.

No bot, no polling loop, no supervisor wrapper — the session never died, only
the interrupted turn did. The three-component pattern — passive account
switcher, durable recurring cron, and idempotent state file read each fire —
is the design the plugin embodies: dispatch.sh treats the flag file as the
single source of truth, so whether the turn that clears it runs 5 seconds or
5 hours after `StopFailure` wrote it, the user-facing effect is identical.

## Configuration

All knobs are `userConfig` entries in `plugin.json`. Set them at install time
via the `/plugin configure` interface or edit the project's
`.claude/settings.json` directly.

| Key | Default | Meaning |
| --- | --- | --- |
| `github_repo` | derived from `origin` remote | Repo slug for `gh pr list`. |
| `trdd_path` | `design/tasks` | Relative path to the TRDD directory. |
| `heartbeat_cron` | `*/5 * * * *` | Cron expression for the heartbeat. |
| `pr_reconciler_interval` | 900 | Min seconds between PR reconciliation passes. |
| `worktree_janitor_interval` | 900 | Min seconds between worktree scans. |
| `trdd_drift_interval` | 3600 | Min seconds between TRDD drift checks. |
| `trdd_reminder_interval` | 14400 | Min seconds between in-progress TRDD reminders. |
| `task_pr_mismatch_interval` | 1800 | Min seconds between task/PR cross-checks. |
| `trdd_staleness_days` | 14 | Days a TRDD can sit `In progress` before drift. |
| `stale_pr_days` | 14 | Days an open PR can sit idle before flagged stale. |
| `stale_task_interval` | 1800 | Min seconds between stale-task scans. |
| `stale_in_progress_threshold` | 7200 | Seconds an `in_progress` task can sit before nudging. |
| `stale_pending_threshold` | 86400 | Seconds a `pending` task can sit before nudging. |
| `dirty_tree_interval` | 300 | Min seconds between dirty-tree checks. |
| `dirty_tree_threshold` | 1800 | Seconds the tree can stay dirty before nudging to commit. |
| `subagent_report_interval` | 3600 | Min seconds between subagent-report scans. |
| `subagent_report_lookback` | 86400 | Age cutoff for reports considered fresh and needing action. |
| `heartbeat_renewal_threshold_days` | 6 | Days after arming before dispatch.sh emits `[janitor-renew]` so Claude re-arms before the 7-day expiry. |

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
- **Heartbeat stopped firing after 7 days**: auto-renewal should have caught
  this — check `.janitor/state/heartbeat-armed-at.ts` and
  `heartbeat-renew-seen.txt`. If Claude was rate-limited or offline during
  the entire renewal window, just run `/janitor-arm` again (idempotent).
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
