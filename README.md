# ai-maestro-janitor

Session-scoped janitor plugin for Claude Code. Reconciles drift between what
the repo actually contains and what the todo list / open PRs / worktrees /
TRDDs claim, and handles rate-limit auto-resume plus prompt-cache keep-alive —
all through Monitors and hooks, no external daemons.

## What it does

Seven monitors run in the background while a Claude Code session is open and
emit a notification only when a new drift event is detected:

| Monitor | Cadence | What it surfaces |
| --- | --- | --- |
| `pr-reconciler` | 15 min | Open PRs whose HEAD is already on main (no-op candidates); PRs idle >14 days. |
| `worktree-janitor` | 15 min | Worktrees whose branch no longer exists or is already merged into main. |
| `trdd-drift` | 1 h | TRDDs marked `In progress` that have not been touched in >14 days. |
| `trdd-reminder` | 4 h | Consolidated reminder of all TRDDs currently `In progress`. |
| `task-pr-mismatch` | 30 min | Session tasks whose status contradicts the state of a referenced PR. |
| `rate-limit-retry` | 2 min | Emits a resume prompt every 2 minutes while a StopFailure (rate-limit) is active. |
| `cache-keepalive` | 30 s poll | Emits a keep-alive nudge after 4m30s of idle so the Anthropic prompt cache stays warm. |

Four hooks coordinate the rate-limit and keep-alive state:

- `SessionStart` initializes state, clears stale flags from prior crashes.
- `UserPromptSubmit` refreshes the idle timer and re-arms the keep-alive flag.
- `Stop` marks a successful turn completion: clears the rate-limit flag,
  resets the retry counter.
- `StopFailure` arms the rate-limit flag; the `rate-limit-retry` monitor
  picks it up on the next tick.

One skill, `/janitor-audit`, lets the user trigger an on-demand aggregate scan
any time.

## Install

This plugin is designed for **project scope only** — install it in the
projects where you want the janitor running, not globally.

```bash
claude plugin marketplace add Emasoft/ai-maestro-plugins
claude plugin install ai-maestro-janitor@ai-maestro-plugins --scope project
```

Then add `.janitor/` (top-level, not under `.claude/`) to the project's
`.gitignore` so the state/logs directory doesn't get committed.

```bash
echo '.janitor/' >> .gitignore
```

## Data layout

All monitor state and logs live at `$CLAUDE_PROJECT_DIR/.janitor/`:

```
<project-root>/.janitor/
├── state/
│   ├── rate-limited.flag
│   ├── rate-limited-since.ts
│   ├── retry-count
│   ├── last-activity.ts
│   ├── keepalive-sent.flag
│   ├── pr-reconciler-seen.txt
│   ├── worktree-janitor-seen.txt
│   ├── trdd-drift-seen.txt
│   ├── trdd-reminder-session-<hash>.txt
│   └── task-pr-mismatch-seen.txt
└── logs/
    ├── pr-reconciler.log
    ├── worktree-janitor.log
    ├── trdd-drift.log
    ├── trdd-reminder.log
    ├── task-pr-mismatch.log
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
| `pr_reconciler_interval` | 900 | Seconds between PR reconciliation passes. |
| `worktree_janitor_interval` | 900 | Seconds between worktree scans. |
| `trdd_drift_interval` | 3600 | Seconds between TRDD drift checks. |
| `trdd_reminder_interval` | 14400 | Seconds between in-progress TRDD reminders. |
| `task_pr_mismatch_interval` | 1800 | Seconds between task/PR cross-checks. |
| `rate_limit_retry_interval` | 120 | Seconds between rate-limit resume prompts. |
| `cache_keepalive_threshold` | 270 | Idle seconds before cache keep-alive fires. |
| `trdd_staleness_days` | 14 | Days a TRDD can sit `In progress` before drift. |
| `stale_pr_days` | 14 | Days an open PR can sit idle before flagged stale. |

## Weekly fallback

Monitors only run while a Claude Code session is open. For coverage during
week-long gaps, this plugin ships a GitHub Actions workflow at
`.github/workflows/weekly-audit.yml` that runs the same drift checks every
Monday at 09:00 UTC and opens a GitHub issue if anything is found.

## Prerequisites

- Claude Code v2.1.105 or later (plugin Monitors).
- `gh` CLI authenticated (`gh auth login`).
- `jq` on `$PATH` (standard on macOS, `apt install jq` on Debian/Ubuntu).
- A git repo with an `origin` remote pointing at GitHub.

## Troubleshooting

- **No notifications after install**: check `claude --debug | grep monitor` at
  session start. If plugin Monitors aren't registering, your Claude Code
  version is probably older than 2.1.105.
- **`pr-reconciler` silent**: inspect `$CLAUDE_PROJECT_DIR/.janitor/logs/pr-reconciler.log`.
  Most common cause is `gh` auth expired — `gh auth status` to check.
- **Duplicate fires**: the dedupe seen-files are per-key. If you want to force
  a re-emit, delete the matching line from
  `$CLAUDE_PROJECT_DIR/.janitor/state/<monitor>-seen.txt`.
- **Cache keep-alive too noisy**: raise `cache_keepalive_threshold` to 3600
  (1 h) if you're using the explicit 1-hour prompt cache.

## License

MIT. See [LICENSE](./LICENSE).
