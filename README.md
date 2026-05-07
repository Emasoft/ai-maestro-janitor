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
| `pr-reconciler` | 15 min | Open PRs whose HEAD is already on main (no-op candidates), PRs that look squash-merged into main, and PRs idle >14 days. Squash-merge detection uses `git commit-tree` + `git cherry` patch-id matching so PRs landed via "Squash and merge" no longer stay flagged forever. |
| `worktree-janitor` | 15 min | Worktrees whose branch no longer exists or has been merged (regular OR squash) into main — emits the exact `git worktree remove` command. Before flagging, requires (a) zero uncommitted changes inside the worktree AND (b) zero unpushed commits past the upstream — either condition is a hard skip with a log line, never a silent removal recommendation. |
| `trdd-drift` | 1 h | TRDDs marked `In progress` that have not been touched in >14 days. |
| `trdd-reminder` | 4 h | Consolidated reminder of all TRDDs currently `In progress`. |
| `task-pr-mismatch` | 30 min | Session tasks whose status contradicts the state of a referenced PR. |
| `stale-task` | 30 min | Tasks stuck `in_progress` >2h or `pending` >24h with no TaskUpdate. Nudges to resume, close, or defer. |
| `dirty-tree` | 5 min | Working tree left uncommitted for >30 min. Reminds to commit often (every commit is a recovery point) and lists safe alternatives when a git safety guard blocks a destructive op: move files to `_dev/`, use `git rm`, `git stash`, or a backup branch. |
| `subagent-report` | 1 h | Recent `.md` reports in `docs_dev/`, `tests/scenarios/reports/`, `scripts_dev/` that have not been referenced in any commit — catches "subagent wrote a findings file that nobody acted on". |
| `version-update` | 24 h | Keeps three versions in sync: the version embedded in the running cron's dispatch path, the highest version installed in the plugin cache, and the latest GitHub release. When the cache is behind GitHub it auto-runs `claude plugin marketplace update` + `claude plugin update --scope <auto>` (gated by `auto_update_on_new_release`, default on); the user is then nudged to `/reload-plugins` + `/janitor-arm` to apply. When the cache is up-to-date but the cron still points at an older installed version (because `/janitor-arm` bakes the path in at arm time), it nudges to `/janitor-arm`. Silent on network/CLI failures and when everything is in sync. |
| `trashcan-purge` | 24 h | Auto-removes timestamped batches in `<project_root>/.trashcan/` whose age exceeds `trashcan_max_age_days` (default 90). Age is computed from the folder-name timestamp (`YYYYMMDD_HHMMSS±HHMM`), not file mtimes — `touch`-ing a file inside an old batch does not extend its life. Markers (`.gitkeep`, `README.txt`) are never touched, so the directory itself persists. Disable via `trashcan_purge_enabled: false`. Emits a single line whenever it actually purges something; silent otherwise. |
| `remote-credentials` | 1 h | URGENT: parses `git remote -v` and flags any remote URL with an embedded password (`https://user:secret@host/...`). Always-on, no userConfig knob to disable — credential leaks via remote URLs are never legitimate. The nudge includes the exact `git remote set-url` command to strip the secret. Always rotate the leaked credential afterwards. |
| `stale-stash` | 24 h | Surfaces git stashes older than `stash_stale_days` (default 30). A forgotten stash is invisible to `git status` and `git log` until a stash conflict on `git pull` reminds you it exists. Emits one line per stash with `git stash show -p <ref>` to inspect and `git stash pop` / `git stash drop` to act. Cross-platform date parsing (GNU + BSD) so it works on Linux CI and macOS dev. |
| `nested-git-safety` | 1 h | URGENT: detects nested `.git` directories (or files, for submodule layout) that are NOT in the parent's `.gitignore`. An unignored nested `.git` can let `git add .` from the parent stage the inner repo's objects, silently corrupting both repos. Emits the exact `.gitignore` line to add or the `git submodule add` command to convert into a proper submodule. Depth-limited (`mindepth 2 maxdepth 4`) and prunes `node_modules/`, `.trashcan/`, etc. so it stays well under the detector budget on large projects. |
| `tracked-ignored` | 1 h | Catches files that are CURRENTLY tracked by git BUT ALSO match a rule in the active `.gitignore`. Typically: a `.env` committed before the rule was added, build artifacts (`dist/`, `*.pyc`), IDE files (`.idea/`, `.vscode/`), OS noise (`.DS_Store`). The list is invisible to plain `git status`. Caches by HEAD SHA so it only re-shells `git ls-files --ignored --cached` when HEAD has moved — saves ~50ms per heartbeat on large repos. |
| `plugin-updates` | 24 h | Auto-installs newer versions of `project`-scope (`<repo>/.claude/settings.json`, committed) and `local`-scope (`<repo>/.claude/settings.local.json`, gitignored) Claude Code plugins for THIS project. Reads the marketplace manifest (refreshed via `claude plugin marketplace update`), compares against the installed version, and runs `claude plugin update <id> --scope <scope>` for each candidate. **Hard-refuses** to touch `user`-scope (global, all-projects) or `managed`-scope (admin-deployed) plugins regardless of configuration — a project-armed janitor has no mandate over global state. Skips the janitor itself (handled by `version-update`). Bails early when no project-scoped plugins exist (~0.4s no-op cost). |
| `mcp-config-drift` | 1 h | Audits the project's MCP server configuration. Reads project-scope MCP from `<project>/.mcp.json` and local-scope MCP from `~/.claude.json` `.projects[<root>].mcpServers` (this project's entry only — user-scope `~/.claude.json` `.mcpServers` is NEVER inspected). Flags: (a) invalid JSON in `.mcp.json` or `~/.claude.json`, (b) `.mcp.json` neither git-tracked nor gitignored (ambiguous scope), (c) servers with no `command` and no `url`, (d) `$VAR` / `${VAR}` references in commands/args/env/headers/url that are unset in the current shell. |
| `settings-scope-drift` | 1 h | Audits the tracking status of `.claude/settings.json` and `.claude/settings.local.json` against their documented purposes. Flags: `.claude/settings.json` is gitignored (project-scope settings won't reach the team), `.claude/settings.local.json` is tracked (personal local-scope settings leak to the team), or either file in ambiguous tracking state. |
| `subagent-scope-drift` | 1 h | Walks `.claude/agents/**/*.md` (Claude Code subagents have no formal local scope, so the git status IS the scope signal: tracked → project, gitignored → personal) and flags every agent file that's neither tracked nor gitignored. Findings are batched into a single drift line with the first 5 + a count, dedup'd by the set of ambiguous files. |
| `claude-md-scope-drift` | 1 h | Audits `CLAUDE.md` / `.claude/CLAUDE.md` (project memory, should be tracked) and `CLAUDE.local.md` (personal memory, should be gitignored) for the same drift classes as `settings-scope-drift`. |

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
- `/janitor-pause [duration]` — suppresses heartbeat output without
  removing the cron. Writes `.janitor/state/paused` with an optional epoch
  expiry; while present, dispatch.sh exits silently. Lighter than
  `/janitor-disarm` — use when starting a focus block or large refactor.
  `/janitor-resume` lifts the pause; if a duration was supplied
  (`/janitor-pause 2h`, `/janitor-pause until 18:00`), the next heartbeat
  after expiry auto-clears the sentinel.
- `/janitor-resume` — removes the paused sentinel. Idempotent (no-op when
  not paused). Does NOT arm the cron — for that, use `/janitor-arm`.
- `/janitor-doctor` — pre-flight health check. Runs ~10 named pass/fail
  checks (state-dir writable, detectors executable, git/gh/jq available,
  `/reports/` + `/reports_dev/` gitignored, plugin.json valid) and prints
  a unicode-bordered table with fix hints for any failures. Read-only —
  safe to run during any session, including paused or disarmed.
- `/janitor-audit` — on-demand aggregate scan. Runs every detector
  synchronously and prints a consolidated markdown report with proposed
  remediation commands (never executed automatically).
- `/janitor-safe-delete <path>...` — recoverable alternative to `rm` for
  any agent. Moves the named paths into
  `<project_root>/.trashcan/<YYYYMMDD_HHMMSS±HHMM>/` (mirroring the original
  layout) plus a sibling `<timestamp>.txt` manifest listing the original
  project-relative paths. Nothing is deleted, the move is reversible on any
  platform via `cp -R` or a manifest-driven `mv` loop. Refuses paths outside
  the project root, the project root itself, and anything inside `.git/`,
  `.claude/`, `.claude-plugin/`, or `.trashcan/`. Reachable via the Skill
  channel or directly via
  `bash $CLAUDE_PLUGIN_ROOT/scripts/safe-delete.sh -- <path>...` for agents
  whose tool surface excludes Skill but includes Bash.

### The `.trashcan/` directory

The first call to `/janitor-safe-delete` in a project bootstraps a
permanent `<project_root>/.trashcan/` directory plus three `.gitignore`
rules:

```text
/.trashcan/*
!/.trashcan/.gitkeep
!/.trashcan/README.txt
```

The trashcan's contents are gitignored so trashed files never leak into a
commit, but `.gitkeep` and `README.txt` are tracked. Tracked files survive
`git clean -fdx` and re-appear on a fresh clone, so the directory itself
remains as permanent infrastructure even though every batch inside it is
ignored. The first-time setup nudges the user to:

```bash
git add .gitignore .trashcan/.gitkeep .trashcan/README.txt
git commit -m "track .trashcan markers"
```

After that commit, the trashcan is bullet-proof against `git clean -fdx`,
clones, and cache-prune sweeps.

To restore a batch:

```bash
# Whole batch (overwrites if names collide at the destination):
cp -R .trashcan/<timestamp>/. ./

# Selective, manifest-driven (works on macOS/Linux/WSL2):
while IFS= read -r p; do
  [ -z "$p" ] || [ "${p#\#}" != "$p" ] && continue
  mv ".trashcan/<timestamp>/${p#./}" "$p"
done < ".trashcan/<timestamp>.txt"
```

To purge a batch permanently:

```bash
rm -rf .trashcan/<timestamp>/ .trashcan/<timestamp>.txt
```

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

On Claude Code v2.1.110+, `claude --resume <session-id>` and
`claude --continue` also resurrect unexpired scheduled tasks, so the
heartbeat survives explicit resume too. On older versions those commands
could leave the cron behind — re-run `/janitor-arm` if no drift lines
surface after an explicit resume.

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
iterating `scripts/detectors/`, so `<detector>` above expands to all nine
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
| `version_check_interval` | 86400 | Min seconds between checks against `api.github.com` for a newer plugin release. |
| `auto_update_on_new_release` | true | When true, the version-update detector runs `claude plugin marketplace update` + `claude plugin update` itself when a newer release is found, then nudges to `/reload-plugins` + `/janitor-arm`. When false, only the manual-update nudge is emitted. |
| `trashcan_purge_enabled` | true | When true, the trashcan-purge detector auto-removes safe-delete batches older than `trashcan_max_age_days`. Set false to disable. |
| `trashcan_max_age_days` | 90 | Days after which a safe-delete batch is auto-purged. Computed from the folder-name timestamp; mtimes inside the batch are ignored. |
| `trashcan_purge_interval` | 86400 | Min seconds between trashcan-purge passes. |
| `stash_stale_days` | 30 | Days a git stash can sit untouched before stale-stash flags it. |
| `stale_stash_interval` | 86400 | Min seconds between stale-stash scans. |
| `remote_credentials_interval` | 3600 | Min seconds between remote-credentials checks. The detector is cheap; the failure mode (credential leak) is severe enough to warrant a relatively fast cadence. |
| `nested_git_safety_interval` | 3600 | Min seconds between nested-`.git` scans. |
| `tracked_ignored_interval` | 3600 | Min seconds between tracked-ignored scans. (HEAD-cached: only re-runs when HEAD has moved since the last check.) |
| `log_retention_days` | 30 | Days of `.janitor/logs/<detector>.log` history to keep. Pruned at most once per UTC day at the top of `dispatch.sh`. Set to `0` to disable retention. |
| `plugin_auto_update_enabled` | true | When true, `plugin-updates` runs `claude plugin update <id> --scope <scope>` automatically. When false, the detector only emits an informational drift line per available update — the user runs the command manually. |
| `plugin_auto_update_scopes` | `local,project` | Comma-separated subset of `{local, project}`. The janitor HARD-REFUSES to touch `user` or `managed` scopes regardless of this value. `project` = `.claude/settings.json` (committed, team-shared); `local` = `.claude/settings.local.json` (gitignored, your personal overrides for this project). |
| `plugin_auto_update_exclude` | `""` | Comma-separated `plugin@marketplace` IDs to skip entirely — useful to pin a specific plugin to its current version when a regression is suspected. |
| `plugin_updates_interval` | 86400 | Min seconds between `plugin-updates` passes. The detector bails in <0.5s when there are no project-scoped plugins; only fires the expensive marketplace refresh when at least one candidate exists. |
| `mcp_config_drift_interval` | 3600 | Min seconds between `mcp-config-drift` passes. Cheap (just JSON parsing + a few `git check-ignore` calls), so a 1-hour cadence is well-affordable. |
| `settings_scope_drift_interval` | 3600 | Min seconds between `settings-scope-drift` passes. Two `git check-ignore` calls. |
| `subagent_scope_drift_interval` | 3600 | Min seconds between `subagent-scope-drift` passes. One `find` plus one `git check-ignore` per agent file. |
| `claude_md_scope_drift_interval` | 3600 | Min seconds between `claude-md-scope-drift` passes. Three `git check-ignore` calls. |

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
