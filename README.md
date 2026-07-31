# ai-maestro-janitor

<p align="center">
  <img src="assets/logo.jpg" alt="ai-maestro-janitor" width="600">
</p>

<!--BADGES-START-->
<!-- The `version-X.Y.Z-blue` spelling is load-bearing: publish.py rewrites this exact
     shape on every release. Renaming it does not break the build — it makes the badge go
     stale silently, which is worse, because a wrong version reads as a true one. -->
[![version](https://img.shields.io/badge/version-1.0.0-blue)](https://github.com/Emasoft/ai-maestro-janitor/releases/latest)
[![CI](https://github.com/Emasoft/ai-maestro-janitor/actions/workflows/ci.yml/badge.svg)](https://github.com/Emasoft/ai-maestro-janitor/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)
<!--BADGES-END-->

Session-scoped janitor plugin for Claude Code. Reconciles drift between what
the repo actually contains and what the todo list / open PRs / worktrees /
TRDDs claim, and handles rate-limit auto-resume plus prompt-cache keep-alive —
all through a single (session-scoped) `CronCreate` heartbeat and hooks. No external
daemons, no monitors.

**Platform:** macOS, Linux, and Windows (everywhere `uv` runs). Required:
[`uv`](https://docs.astral.sh/uv/) (every script is a `uv run --script`
PEP 723 file with `requires-python = ">=3.10"`), `git`, and `gh` (for the
detectors that talk to GitHub). No `bash`-specific syntax left in the hot
path; the only remaining shell wrapper is the cron back-compat shim.

## How it works

One recurring cron — session-scoped, re-armed each session — is armed on session start via the `/janitor-arm`
skill. From v0.4.11 the cron prompt points at an **auto-rolling stub** in
`${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py` — a stable path that lives
OUTSIDE the version-stamped plugin cache. The stub re-resolves the
highest cached plugin version on every fire and `os.execv`'s into its
`scripts/dispatch.py`, so plugin updates roll forward automatically:
the cache picks up the new version, the next heartbeat targets it,
no `/janitor-arm` re-run needed. Re-arming is now only required (1)
on first install, (2) once when upgrading from pre-stub (≤ v0.4.10)
to v0.4.11+, and (3) before the 7-day cron auto-expiry in response to
the `[janitor-renew]` nudge.

Each cron fire is a fresh user turn that runs `dispatcher-stub.py` →
`scripts/dispatch.py`:

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
window clears. For how the heartbeat, the daemon, and the OS keepalive keep
each other alive through crashes and bad self-updates, see
[Immortality](#immortality-self-healing-daemon).

### Inside an ai-maestro agent (harness mode)

Since v0.50.0 the same plugin detects at runtime whether it is running inside an
[ai-maestro](https://github.com/Emasoft/ai-maestro) harness agent and switches to a
**thin** mode there: the per-workdir detectors keep running, but the plugin spawns **no
global daemon** and performs **no writes outside the agent's own project** — session
continuity (rate-limit resume, compaction resume) is delegated to the ai-maestro server,
which acts as the daemon for its agents. Outside the harness nothing changes (full mode,
as described above). A standalone janitor daemon on the same machine detects
server-managed agents and leaves them strictly alone, and machine-wide once-only chores
(marketplace refresh, plugin updates, OAuth keepalive) are coordinated so the two daemons
never do the same chore twice — per capability CLASS, driven by the server's auth-free
liveness probe file (the contract co-ratified with ai-maestro in
`design/ARCHITECTURE.md`). All automatic notifications are channeled strictly
per-project: no agent ever receives another project's findings.

### The findings ledger and the human channel (v0.51.0)

Every finding the janitor raises is indexed in the affected project's own
`.janitor/state/findings-ledger.ndjsonl` — an append-only, capped, per-project mailbox
(one sanitized JSON line per finding, pointing at the ticket/TRDD that carries the full
report). The next session in that project sees its unread findings at session start
(at most ~10 concise lines) and can browse them with `/janitor-findings` (list /
`show <ref>` / ack). When a finding concerns machinery no session owns — a quarantined
daemon task, an OAuth-rotator degradation, a fleet repo-config gap — the daemon pushes
ONE severity-gated, deduplicated, daily-capped notification to the human: a native
desktop notification by default, plus an optional generic webhook
(`notify_webhook_url` in the plugin config — one HTTPS POST covers Slack, Telegram,
Discord, ntfy.sh). Token telemetry follows the same quietness rule: burn-rate alarms
surface only in the project actually driving the burn.

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
| `version-update` | 5 min | Keeps three versions in sync: the version embedded in the running cron's dispatch path, the highest version installed in the plugin cache, and the latest GitHub release. When the cache is behind GitHub it auto-runs `claude plugin marketplace update` + `claude plugin update --scope <auto>` (gated by `auto_update_on_new_release`, default on); the user is then nudged to `/reload-plugins` + `/janitor-arm` to apply. When the cache is up-to-date but the cron still points at an older installed version (because `/janitor-arm` bakes the path in at arm time), it nudges to `/janitor-arm`. Silent on network/CLI failures and when everything is in sync. |
| `trashcan-purge` | 24 h | Auto-removes timestamped batches in `<project_root>/.trashcan/` whose age exceeds `trashcan_max_age_days` (default 90). Age is computed from the folder-name timestamp (`YYYYMMDD_HHMMSS±HHMM`), not file mtimes — `touch`-ing a file inside an old batch does not extend its life. Markers (`.gitkeep`, `README.txt`) are never touched, so the directory itself persists. Disable via `trashcan_purge_enabled: false`. Emits a single line whenever it actually purges something; silent otherwise. |
| `remote-credentials` | 1 h | URGENT: parses `git remote -v` and flags any remote URL with an embedded password (`https://user:****@host/...`). Always-on, no userConfig knob to disable — credential leaks via remote URLs are never legitimate. The nudge includes the exact `git remote set-url` command to strip the secret. Always rotate the leaked credential afterwards. |
| `stale-stash` | 24 h | Surfaces git stashes older than `stash_stale_days` (default 30). A forgotten stash is invisible to `git status` and `git log` until a stash conflict on `git pull` reminds you it exists. Emits one line per stash with `git stash show -p <ref>` to inspect and `git stash pop` / `git stash drop` to act. Cross-platform date parsing (GNU + BSD) so it works on Linux CI and macOS dev. |
| `nested-git-safety` | 1 h | URGENT: detects nested `.git` directories (or files, for submodule layout) that are NOT in the parent's `.gitignore`. An unignored nested `.git` can let `git add .` from the parent stage the inner repo's objects, silently corrupting both repos. Emits the exact `.gitignore` line to add or the `git submodule add` command to convert into a proper submodule. Depth-limited (`mindepth 2 maxdepth 4`) and prunes `node_modules/`, `.trashcan/`, etc. so it stays well under the detector budget on large projects. |
| `tracked-ignored` | 1 h | Catches files that are CURRENTLY tracked by git BUT ALSO match a rule in the active `.gitignore`. Typically: a `.env` committed before the rule was added, build artifacts (`dist/`, `*.pyc`), IDE files (`.idea/`, `.vscode/`), OS noise (`.DS_Store`). The list is invisible to plain `git status`. Caches by HEAD SHA so it only re-shells `git ls-files --ignored --cached` when HEAD has moved — saves ~50ms per heartbeat on large repos. |
| `plugin-updates` | 5 min | Auto-installs newer versions of `project`-scope (`<repo>/.claude/settings.json`, committed) and `local`-scope (`<repo>/.claude/settings.local.json`, gitignored) Claude Code plugins for THIS project. Reads the marketplace manifest (refreshed via `claude plugin marketplace update`), compares against the installed version, and runs `claude plugin update <id> --scope <scope>` for each candidate. **Hard-refuses** to touch `user`-scope (global, all-projects) or `managed`-scope (admin-deployed) plugins regardless of configuration — a project-armed janitor has no mandate over global state. Skips the janitor itself (handled by `version-update`). Bails early when no project-scoped plugins exist (~0.4s no-op cost). |
| `marketplace-refresh` | 5 min | **v0.5.4+: scoped per-session refresh.** Spawns a detached worker that runs `claude plugin marketplace update <name>` ONCE per unique marketplace hosting plugins enabled in `<project>/.claude/settings.json` (project scope) and `<project>/.claude/settings.local.json` (local scope) — never the global bulk refresh. Global / user-scope marketplaces are owned by the central daemon (`daemon_marketplace_refresh_interval`, default 20 min). Keeping the per-session detector narrow means N concurrent sessions cannot pile up overlapping bulk refreshes ([issue #7](https://github.com/Emasoft/ai-maestro-janitor/issues/7)). PID tracked in `.janitor/state/marketplace-refresh.pid`; overlapping fires skip when the prior worker is still alive. Also keeps the daemon-staleness watchdog: surfaces a drift line at most once per UTC hour when the daemon's `marketplace-refresh.last-run.ts` is older than 2× cadence. |
| `user-plugins-update` | 5 min | **v0.5.2+: per-session shim.** Same shape as `marketplace-refresh` — calls `ensure_daemon_running()` and exits silently. The actual `claude plugin list --json` enumeration + per-plugin `claude plugin update <id> --scope user` sweep is now in the daemon (sequential, one global instance). Pre-daemon this was a "Track 1 of the auto-update directive" detector running an entire sweep PER SESSION, producing the cross-session pile-up [issue #7](https://github.com/Emasoft/ai-maestro-janitor/issues/7) documents. Surfaces a stale-daemon drift line at most once per UTC hour when the daemon's `user-plugins-update.last-run.ts` is older than 2× cadence. |
| `local-plugins-update` | 5 min | **Track 2a of the auto-update directive — per-project, no git mutation.** Reads `<project>/.claude/settings.local.json` directly (the file is gitignored by Claude Code convention — personal overrides for this project), filters `enabledPlugins` to entries with `true` (only those enabled locally, per the directive), then spawns a detached worker that runs `claude plugin update <id> --scope local` per plugin. The worker PID is tracked in `.janitor/state/local-plugins-update.pid`; overlapping fires skip cleanly. Bails in <100ms when settings.local.json doesn't exist. Per-project — a janitor armed in project A only updates project A's local-scope plugins. Silent on stdout. Logs to `.janitor/logs/local-plugins-update.log`. |
| `project-plugins-update` | 5 min | **Track 2b of the auto-update directive — per-project, Claude-driven commit on git drift.** Reads `<project>/.claude/settings.json` (git-tracked, team-shared), filters `enabledPlugins` to entries with `true`, then spawns a detached worker that runs `claude plugin update <id> --scope project` per plugin. After the sweep, if `.claude/settings.json` is now dirty (via `git status --porcelain -- .claude/settings.json`), the worker writes a commit-pending sentinel; the next heartbeat's parent run reads it and emits a single drift line of the form `[project-plugins-commit-needed] N project-scope plugin(s) updated: <ids>. Run exactly: git commit --only -- .claude/settings.json -m $'janitor chore: commit the updated plugins\\n\\nplugins updated:\\n  - <id1>\\n  - <id2>'` followed by the exact command on its own line. Claude in the heartbeat turn executes the command — signing, pre-commit hooks, branch protection rules, signed-tag policies are all honored automatically because the commit uses porcelain `git commit` with the user's git config. **Whitelist is enforced — only `.claude/settings.json` is ever named.** No flock coordination needed, no signing detection logic, no `--no-verify`. Logs to `.janitor/logs/project-plugins-update.log`. |
| `mcp-config-drift` | 1 h | Audits the project's MCP server configuration. Reads project-scope MCP from `<project>/.mcp.json` and local-scope MCP from `~/.claude.json` `.projects[<root>].mcpServers` (this project's entry only — user-scope `~/.claude.json` `.mcpServers` is NEVER inspected). Flags: (a) invalid JSON in `.mcp.json` or `~/.claude.json`, (b) `.mcp.json` neither git-tracked nor gitignored (ambiguous scope), (c) servers with no `command` and no `url`, (d) `$VAR` / `${VAR}` references in commands/args/env/headers/url that are unset in the current shell. |
| `settings-scope-drift` | 1 h | Audits the tracking status of `.claude/settings.json` and `.claude/settings.local.json` against their documented purposes. Flags: `.claude/settings.json` is gitignored (project-scope settings won't reach the team), `.claude/settings.local.json` is tracked (personal local-scope settings leak to the team), or either file in ambiguous tracking state. |
| `subagent-scope-drift` | 1 h | Walks `.claude/agents/**/*.md` (Claude Code subagents have no formal local scope, so the git status IS the scope signal: tracked → project, gitignored → personal) and flags every agent file that's neither tracked nor gitignored. Findings are batched into a single drift line with the first 5 + a count, dedup'd by the set of ambiguous files. |
| `claude-md-scope-drift` | 1 h | Audits `CLAUDE.md` / `.claude/CLAUDE.md` (project memory, should be tracked) and `CLAUDE.local.md` (personal memory, should be gitignored) for the same drift classes as `settings-scope-drift`. |
| `cross-scope-reference-drift` | 1 h | Enforces SCOPE PARITY between a source (agent/skill/command/CLAUDE.md) and the targets it references. Reference points scanned: BODY → `/<name>` slash-commands and `Skill('<name>')` invocations. FRONTMATTER → `agent: <name>` (skills/commands with `context: fork`), `Skill(<name>...)` patterns inside `allowed-tools:`, and `skills: [<a>, <b>]` lists in subagent frontmatter (preloaded skills). Two drift classes: **(a) silent-clone-break** — tracked source → gitignored or ambiguous target (source ships, target doesn't, reference dangles). **(b) scope-mismatch** — gitignored source → tracked target (local source has a hidden dependency on team-shared infrastructure). Each drift line includes both possible fix paths. References that don't resolve to a project-local file (built-ins, plugin commands, URLs) are silently skipped — no false positives. |
| `workflow-security` | 5 min | URGENT: runs the janitor's native Sentinel scanner (regex + structural + repo tiers — the same engine `/janitor-github-workflow-doctor` drives) over `.github/workflows/` and surfaces NEW CRITICAL/HIGH findings (template injection, secret leaks, unpinned third-party actions, dangerous `pull_request_target` checkout, …) as a single drift line pointing at the doctor skill for the full report + per-finding fixes. MAJOR/MINOR hardening is left to the on-demand skill so the heartbeat stays signal-dense. Content-hashes every workflow file and short-circuits when nothing changed, so an unchanged-workflows fire is ~free while a freshly-introduced vulnerability surfaces within one cadence (≤5 min) — reverting a fix back to a vulnerable version re-alerts (it is a hash transition). READ-ONLY — never edits a workflow. Disable via `workflow_security_enabled: false`. |
| `branch-protection` | 6 h | URGENT: asks the GitHub API (READ-ONLY) whether the default branch is covered by classic branch protection OR an active branch ruleset (inherited org/enterprise rulesets count). Surfaces a drift line — with the exact `Settings → Rules → Rulesets` remediation — ONLY when it can DEFINITIVELY confirm neither is present, so an unprotected repo where anyone with write access can force-push, rewrite history, or delete the branch can never go unnoticed. Skips silently when `gh` is absent/unauthenticated, the viewer is not a repo admin (can't fix it anyway), there's no GitHub remote, or any probe is indeterminate (no false alarms). Nags once until fixed and re-arms automatically (`emit_forget`) if protection is later removed. NEVER configures protection itself — it surfaces, you (or an explicitly-authorised guard mode) act. Disable via `branch_protection_enabled: false`. |
| `package-manager-policy` | 6 h | Detection complement to the `pre-tool-pkg-guard` PreToolUse hook — where the hook PREVENTS weakening at call-time, this detector REPORTS pre-existing gaps so a project can be hardened before the next supply-chain attack lands. Scans `.npmrc`, `package.json#pnpm`, `pnpm-workspace.yaml`, `.yarnrc.yml`, `bunfig.toml` for missing or weakened safety knobs (`minimumReleaseAge` < threshold, `trustPolicy != no-downgrade`, `blockExoticSubdeps != true`, `audit-level` lowered, yarn `enableScripts: true`, bun `[install].verify = false`). Also flags when **neither `sfw` nor `safe-chain` is on PATH** (no install-time malware firewall). Silent on non-node projects. Content-hashed: unchanged config → silent. Disable via `pkg_manager_policy_enabled: false`. |
| `oauth-cookie-reminder` | 6 h | **Opt-in (OAuth account rotator), macOS.** Silent unless a rotator home with a `state.json` exists. Compares each captured account's claude.ai session-cookie lifetime against its OAuth-token lifetime and reminds you (machine-scoped daily dedupe) to refresh a login BEFORE a cookie expires while OAuth is still healthy — so the two expiries never coincide and leave no working account to refresh from. Reads slots keychain-first. |
| `oauth-login-needed` | 6 h | **Opt-in (OAuth account rotator), macOS.** Silent unless a rotator home exists. Surfaces the accounts that need a ONE-TIME human login — the ones that can neither self-renew (no refresh token) nor auto-bootstrap (no live claude.ai session) — naming the exact `~/.claude/account-rotator/open-login.sh <email>` (opens a DEDICATED Chrome window; your default browser stays untouched). A secondary `[oauth-capture-stalled]` line covers logged-in-but-not-yet-captured accounts. After you log in once, the daemon auto-bootstraps a refresh-bearing slot and the account self-renews thereafter (TRDD-32acd15f). |

The heartbeat cron runs every 5 minutes by default (`*/5 * * * *`), so the
detectors fire at roughly their configured cadence without any additional
bookkeeping. The heartbeat prompt is intentionally minimal (~20 tokens of
user text) to keep per-fire overhead low.

## Global janitor daemon (since v0.5.2)

`scripts/daemon.py` is a single OS-wide process that owns every machine-global
auto-update task — the bulk `claude plugin marketplace update` (all configured
marketplaces, every 20 min), the user-scope plugin sweep (`claude plugin
update <id> --scope user` over every user-scope plugin, every 1 h), and the
janitor self-update (every 6 h, gated by `auto_update_on_new_release`). It is
**lazy-spawned** by any per-session heartbeat via
`lib.global_state.ensure_daemon_running()` and **singleton-protected** by an
exclusive flock on `<global-state>/daemon.flock`, so N
concurrent Claude Code sessions across N projects produce exactly **one**
daemon — not N. This closes [issue #7](https://github.com/Emasoft/ai-maestro-janitor/issues/7):
pre-daemon, per-project PID dedup could not coordinate across sessions, so
each session's heartbeat spawned its own `claude plugin marketplace update`
worker, piling them up until the workstation ran out of memory.

Narrower per-session marketplace work — refreshing only the few marketplaces
hosting `local`/`project`-scope plugins enabled in THIS project — stays on
the per-session detector (`marketplace-refresh`, 5 min cadence). The daemon
and the per-session refresh have disjoint scopes: the daemon does the global
bulk, the session does the project-narrow set.

`<global-state>` below is the daemon-state dir. Since TRDD-2U8AH82F its
CANONICAL home is the plugin DATA dir
`~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/`
(backed up, preserved across updates, purged only on uninstall). An existing
install is migrated automatically: the daemon copies the legacy
`~/.claude/janitor-global-state/` there one time under its singleton flock and
stamps a `migrated-from-legacy.ts` marker; until that happens everything keeps
using the legacy dir, and afterwards the legacy dir remains only as a
tombstoned read-fallback for not-yet-updated sessions.

| State file | Purpose |
| --- | --- |
| `<global-state>/daemon.flock` | exclusive flock held for the daemon's lifetime; the kernel releases it on death |
| `<global-state>/daemon.pid` | the live daemon's PID (diagnostic) |
| `<global-state>/daemon.heartbeat.ts` | tick written every loop iteration + during long workloads; sessions treat the daemon as stuck when this is older than `DEFAULT_DAEMON_STALE_SECONDS` (1800 s) |
| `<global-state>/marketplace-refresh.last-run.ts` | last successful bulk-refresh completion stamp |
| `<global-state>/user-plugins-update.last-run.ts` | same, for the user-scope plugin sweep |
| `<global-state>/version-update.last-run.ts` | same, for the janitor self-update task |
| `<global-state>/reload-needed.flag` | written by the daemon when a real plugin update lands; the next heartbeat emits `[janitor-reload]` and clears the flag |
| `<global-state>/daemon.log` | daemon's own log (rotated by `state.rotate_log_if_big`) |
| `<global-state>/kill-switch.flag` | touch to make the running daemon exit on its next loop tick |
| `<global-state>/migrated-from-legacy.ts` | the migration marker — its presence is what flips path resolution to the DATA dir |

**Manual control** (substitute `<global-state>` with the DATA-dir path above —
or the legacy path on a not-yet-migrated install):
- Inspect: `tail -30 <global-state>/daemon.log`
- Disable temporarily: `touch <global-state>/kill-switch.flag`
- Re-enable: `rm <global-state>/kill-switch.flag` (the next
  heartbeat lazy-spawns a fresh daemon)
- Disable permanently: set `daemon_enabled: false` in userConfig
- Kill (graceful): `kill $(cat <global-state>/daemon.pid)`

The daemon NEVER touches per-project plugin state (`local-plugins-update`,
`project-plugins-update`, `plugin-updates` remain per-session) and NEVER
modifies your repos — it only operates on `~/.claude/plugins/`.

## Immortality (self-healing daemon)

Across v0.21.0 → v0.24.1 the janitor gained a self-healing spine so an
unattended overnight session keeps running through crashes, bad self-updates,
compaction, and frozen sessions. The full design lives in the
[CLAUDE.md project map](./CLAUDE.md) and
`design/tasks/TRDD-*-fe45babc-*.md`; the summary:

**Four layers, each resurrecting the one below.** L0 — an OS keepalive
(macOS launchd LaunchAgent with `KeepAlive`+`RunAtLoad`, Linux systemd user
unit with `Restart=always`) respawns the global daemon on crash, logout, or
reboot **even with zero Claude sessions open** — closing the circular gap
where a dead daemon can't restart the very sessions whose heartbeats would
restart it. L1 — the [global singleton daemon](#global-janitor-daemon-since-v052).
L2 — the [session hooks](#hooks) that re-arm and resume. L3 — the in-session
cron [heartbeat](#how-it-works). A session heartbeat still lazy-spawns the
daemon (L3→L1); the OS keepalive is the floor that holds when no session is
alive.

**Self-integrity — never run a corrupted or tampered self.** Before
`os.execv`-ing into a cached version, the auto-rolling stub verifies it
against its shipped integrity manifest (C2), pins the last-*GOOD* version and
quarantines a proven-bad one (C3), and auto-rolls-back a crash-looping bad
self-update to the last good version (C4). This now runs at **both** the
heartbeat path **and** the daemon / L0 keepalive path (the keepalive's
version selection skips quarantined versions, so a bad-*daemon* update can't
self-resurrect via launchd forever). The trust-anchor files (HMAC key,
last-good pin, quarantine list) live in the fixed DATA dir, *outside* the
cache being verified, so a tampered version can't forge them. **Cardinal rule:
FAIL-OPEN** — a version that *can't* be checked is accepted; only one *proven*
corrupt is rejected, because a dead heartbeat is worse than a maybe-corrupt
one.

**OS-keepalive resilience.** The service config bakes a concrete absolute
interpreter so launchd/systemd can start the daemon even when their login PATH
lacks `python3` (D-α). And the OS entry point runs a pre-launch verify-or-restage
of the staged daemon closure (D-β) — a torn or truncated DATA stage self-heals
from the trusted cache instead of crash-looping.

**Fleet guardian.** A daemon beat (`task_session_liveness`) detects a
frozen / rate-limited session and recovers it via a **gentle ladder** —
ESC-nudge → `/janitor-arm` re-arm → `/reload-plugins` — terminal-env-aware
(iTerm / tmux / ai-maestro). The process-**killing** hard-restart rungs
(kill + relaunch) exist but are **default-OFF and opt-in**
(`CLAUDE_PLUGIN_OPTION_FLEET_HARD_RESTART_ENABLED`), so the guardian never
kills your active session; a crash-loop guard pages a human instead of a
restart storm. Detection always runs and logs; firing the gentle rungs is on
by default (`CLAUDE_PLUGIN_OPTION_FLEET_RECOVERY_ENABLED=0` for dry-run-log-only).

**Recovery audit log.** Every recovery decision (which rung fired, on which
session, when, outcome) is appended to a tamper-evident HMAC-chained NDJSON
log — a pure forensic side-channel that, like every immortality call, is
FAIL-OPEN: a logging fault never perturbs the survival-critical recovery beat.

The opt-in / safety knobs above (`CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE`,
`CLAUDE_PLUGIN_OPTION_FLEET_RECOVERY_ENABLED`,
`CLAUDE_PLUGIN_OPTION_FLEET_HARD_RESTART_ENABLED`) are environment options
read directly by the daemon — set them in your project's
`.claude/settings.json` `env` block.

## Hooks

- `SessionStart` initializes `.janitor/state/`, refreshes the idle timer, and
  prints a one-line context reminder to run `/janitor-arm`.
- `UserPromptSubmit` refreshes the idle timer.
- `Stop` refreshes the idle timer after a successful turn.
- `StopFailure` writes `rate-limited.flag`; the next heartbeat fire picks it
  up and emits `[janitor-resume]`.
- `PreToolUse` (since v0.5.2): `pre-tool-pkg-guard.py` refuses
  package-manager safety-bypass attempts on `Bash` / `Edit` / `Write` calls.
  Closes [issue #8](https://github.com/Emasoft/ai-maestro-janitor/issues/8) —
  the user-scope guardrail Atai Barkai called for after the 2026-05
  art-template npm supply-chain compromise. Two classes of violation:
  - **Class A — Bash bypass flags.** Whitespace-normalised regex match
    over the full command. Catches `pnpm install --no-frozen-lockfile`,
    `pnpm install --no-verify-store-integrity`, `pnpm config set
    minimumReleaseAge N` where N is below the threshold, `npm install
    --no-integrity`, `npm config set audit-level none|info|low`,
    `yarn config set enableScripts true`, `bun install --no-verify`,
    `corepack disable`, etc. Backslash-newline continuations cannot
    evade the match.
  - **Class B — Weakening edits.** Parses the before-state on disk and
    the after-state after applying the Edit / Write, compares guarded
    keys in `.npmrc`, `package.json#pnpm`, `pnpm-workspace.yaml`,
    `.yarnrc.yml`, `bunfig.toml`. Denies when `minimum-release-age` /
    `minimumReleaseAge` is lowered or removed, when `trust-policy` /
    `trustPolicy` is set to anything other than `no-downgrade`, when
    `blockExoticSubdeps` flips from true to false, when `audit-level`
    is lowered below `moderate`, when yarn `enableScripts` flips
    false→true, or when bun `[install].verify=true` is removed.

  Default behaviour is **hard deny** with a one-line reason naming the
  bypass and the userConfig knob to relax it; set
  `pkg_manager_hook_allow_user_override: true` to downgrade to per-call
  `ask` instead. Every block lands in
  `<global-state>/pkg-manager-guard.log` (the daemon-state dir — see the
  Global daemon section for its canonical DATA-dir path).

  Sample deny reason: `[pkg-manager-guard] pnpm --no-frozen-lockfile
  permits lockfile drift (use a real lockfile update + commit). Set
  CLAUDE_PLUGIN_OPTION_PKG_MANAGER_HOOK_ALLOW_USER_OVERRIDE=true to confirm
  per call, or raise CLAUDE_PLUGIN_OPTION_PKG_MANAGER_MIN_RELEASE_AGE_MINUTES
  if the threshold is wrong.`
- **Context-compact watchdog** — `PreToolUse` `pre-tool-context-usage.py` +
  `PostCompact` `post-compact-resume.py` (DEFAULT-ON; `context_watchdog_enabled =
  true`). Claude Code's native auto-compact is unreliable on the 1M window —
  sessions run past the threshold, sometimes to ~999k where `/compact` itself
  can no longer run (forcing a total-loss `/clear`). The watchdog puts the
  agent in the loop instead, as a four-stage cycle:
  - **Producer** — your statusline writes the live context % to a project-local
    `<project>/.claude/janitor/context-usage.<session>.json` (throttled ≤ 1/10 s).
  - **Consumer** — `pre-tool-context-usage` (`PreToolUse`, all tools) reads that
    snapshot and injects `Context window: NN% …` into the agent's context before
    every tool call. In its advisory tier it emits **no `permissionDecision`**, so
    the tool's normal permission flow is untouched: at/above `context_compact_suggest_pct`
    (default 60) it appends a nudge to run `/janitor-compact-context`. Near the cap
    (at/above `context_hardstop_pct`, default 85, gated by `context_autocompact_enabled`)
    it switches to **enforcement** — it queues the compaction itself and **denies** the
    tool call so the turn ends cleanly for `/compact`, after which `post-compact-resume`
    continues at a reduced context. Fail-open: no automatable terminal or any error
    degrades back to the advisory, never a stuck deny.
  - **Trigger** — the agent invokes `/janitor-compact-context`, which records a
    one-shot resume directive then fires a detached ESC→`/compact` at ONLY its
    own iTerm pane (matched by `$ITERM_SESSION_ID` UUID — never other panes; the
    UUID is strictly validated before it reaches `osascript`).
  - **Resume** — `post-compact-resume` (`PostCompact`) reads the directive and
    writes `resume-after-compact.flag`; the next heartbeat emits
    `[janitor-resume] …continue TRDD-xxxx…` and the agent resumes the work.

  This closes the loop so an unattended overnight session compacts itself before
  the wall and resumes — instead of stalling idle. **Off by default** (the
  consumer fires on every tool call). The self-trigger is iTerm-only; outside
  iTerm the skill still records the resume directive and asks you to run
  `/compact`. Note: two sessions sharing the *exact same* working directory
  share the resume flag (worktrees are already isolated); the per-session
  context snapshot is always session-keyed.

## Supply-chain defense stack

After the 2026-05 `art-template` npm compromise (25k weekly downloads, ~5
days from malicious publish to detection), defense in depth across four
distinct layers is the documented best practice. The janitor covers three
layers natively and cross-links to two external tools for the fourth (the
malware-DB layer, which cannot be defended without a continuously-curated
threat feed).

| # | Layer | What it stops | Provided by |
| --- | --- | --- | --- |
| 1 | **CI workflow hardening** — static analysis | Template-injection, unpinned actions, missing permissions, `pull_request_target` checkout-from-fork, secret leaks in workflow YAML | `workflow-security` detector (every heartbeat) + `/janitor-github-workflow-doctor` (deep, on-demand) — both shell out to [`zizmor`](https://github.com/zizmorcore/zizmor) and run the janitor's native Sentinel rule set |
| 2 | **Repo hardening** — branch protection | Force-push to default branch, branch deletion, merge-without-review, history rewrite | `branch-protection` detector (read-only `gh api` check) |
| 3a | **Config hardening — prevention** | Agent silently lowers `minimumReleaseAge`, disables integrity checks, re-enables postinstall scripts to bypass a stuck install | `pre-tool-pkg-guard` PreToolUse hook (every Bash/Edit/Write) |
| 3b | **Config hardening — detection** | Project never set the safety knobs in the first place (`minimumReleaseAge` missing / weak `trustPolicy` / `blockExoticSubdeps` off / no install-time firewall on PATH) | `package-manager-policy` detector (every 6 h) |
| 4 | **Install-time malware DB** | A package published to npm/yarn/pnpm/pip/poetry IS confirmed malicious — blocks the download before it lands in `node_modules/` | **External** — install one of: [Socket Firewall Free (`sfw`)](https://docs.socket.dev/docs/socket-firewall-free) (prefix-based wrapper, no global shim; safest for uv-heavy environments), [Aikido `safe-chain`](https://github.com/AikidoSec/safe-chain) (PATH shim; broadest ecosystem incl. poetry/uv) |
| 5 | **Action-ref hygiene** | GHA workflows using floating tags (`@v4`) instead of pinned SHAs | Detection: `workflow-security` (Sentinel `github-dependency-refs`). Bulk fix: [`actions-up`](https://github.com/azat-io/actions-up) (`npx actions-up`) |
| 6 | **Advisory matching** — installed deps vs. known-bad list | A previously-fine version is now disclosed as malicious (Shai-Hulud-class worm); your lockfile pins a vulnerable version | `/janitor-supply-chain-watcher` (queries GHSA + OSV.dev; on-demand) |

The hook (3a) and the detector (3b) share the same `pkg_manager_min_release_age_minutes`
threshold (default 7200 = ~5 days). Layers 1, 2, 3a, 3b, 6 run unattended at
their cadences; layer 4 needs ONE explicit install action by you; layer 5 is
on-demand when the doctor flags unpinned refs.

### The single security agent

When any security detector finds drift, the heartbeat now **suggests** running
**`/janitor-security-agent`** (or `claude --agent janitor-security-agent`) — ONE
agent that runs *every* security skill above and both **DETECTS and FIXES**,
fail-safe. It mirrors the memory subconscious agent (one agent, many skills, its
own context): each launch handles one security domain (or a `full-sweep`) and
loads only that domain's skill. It **auto-fixes what is safe** (dependency bumps
with the tests re-run green, GitHub-workflow hardening via zizmor, the hardened
`dependabot.yml`, the ratified branch-protection baseline, prompt-injection
sanitization) and **FLAGS what needs a human** (live credential *rotation*,
history purge, production secrets) — it never auto-rotates a credential, never
force-pushes, and never suppresses a finding to pass a gate. It honors
`/janitor-autofix-off` (detect + flag only). Opt out of the heartbeat suggestion
with `CLAUDE_PLUGIN_OPTION_SECURITY_AGENT_HINT=false`.

## Skills

- `/janitor-arm` — arms (or renews) the heartbeat cron. Idempotent: replaces
  any existing `[janitor-heartbeat]` job. Run once per session to start, and
  whenever Claude surfaces a `[janitor-renew]` nudge — the skill also writes
  the arm-timestamp that feeds the auto-renewal check.
- `/janitor-disarm` — stops the heartbeat cron. Deletes every
  `[janitor-heartbeat]` job, clears the arm-timestamp, and suppresses the
  renewal nudge. Use to pause janitor activity without uninstalling.
- `/janitor-global-disarm` · `/janitor-global-arm` — the global-scope
  counterparts of the two local commands above, acting on the machine-wide
  daemon and every Claude Code instance at once (see
  [Control commands](#control-commands-severity--scope)). Backed by
  `scripts/global_control_cli.py disarm|arm|status`.
- `/janitor-memory-record-recent` — user-invoked harvest of recent changes
  into the **Wikimem** (the project's markdown memory system) — the active
  counterpart of the `memorize-nudge` heartbeat detector (which only
  *surfaces* a nudge when code outran the wiki; this command actually does
  the write).
- `/janitor-autofix-off` — opt out of the "act, don't ask" policy in this
  project. After running, the janitor still surfaces security / CI / publish
  findings but Claude must ASK before applying fixes. Writes
  `.janitor/state/autofix-mode.txt = off`. The heartbeat emits a once-per-day
  `[autofix-off]` reminder so the silence is visible.
- `/janitor-autofix-on` — flip autofix back to the default. Removes the
  sentinel (or overwrites with `on`). Idempotent; no-op when already on.
- `/janitor-branch-protection-setup` — one-shot interactive setup of the
  ratified two-ruleset branch-protection baseline (janitor #14 /
  maintainer #7) on the project's default branch:
  `baseline-history-protect` (force-push block + deletion block +
  linear-history, no bypass) and `baseline-pr-and-checks` (1-approval PR
  review with dismiss-stale + thread-resolution + strict
  required-status-checks, with the repo-admin role granted an
  always-bypass so a solo admin is not self-locked). Both target the
  `~DEFAULT_BRANCH` magic ref (byte-identical with the maintainer
  plugin). The required status checks are **auto-detected** from the
  repo's live CI check-runs at apply time (empty when CI has not run yet
  — never hard-coded). Tier 1 user-invoked surface for TRDD-631fa3de
  Option B: the skill shows BOTH EXACT JSON payloads (with the resolved
  checks) before applying and waits for confirmation. Idempotent-by-name
  — each ratified ruleset is PATCHed if present else POSTed, so
  re-running never duplicates; an orphaned pre-migration
  `janitor-baseline` ruleset is deleted once both ratified rulesets are
  confirmed in place. Refuses when `gh` is missing, the viewer is not
  admin on the repo, or no `repository` URL is declared. For the silent
  Tier 2 auto path (no human in the loop), flip
  `guard_mode_enabled = true` in plugin.json — same baseline, applied
  by `scripts/guard/branch_protection_apply.py` on the heartbeat.
- `/janitor-actions-up` — bulk SHA-pin + update every GitHub Actions
  reference under `.github/workflows/`. Wraps Azat-io's [`actions-up`](https://github.com/azat-io/actions-up)
  CLI behind a safety harness: dry-run preview first, configurable
  `--min-age` gate (default 5 days, matching the project's
  `pkg_manager_min_release_age_minutes` floor), `--mode` to control
  major/minor/patch upgrade scope, self-scan guard that refuses on the
  janitor's own repo. Pairs with `workflow-security` (surveillance) —
  this skill is the one-shot heal that closes every Sentinel
  `github-dependency-refs` finding in one pass. Refuses on a dirty
  working tree so the diff lands as a single discrete commit.
- `/janitor-doctor` — pre-flight health check. Runs ~12 named pass/fail
  checks (state-dir writable, detectors executable, uv/git/gh available,
  `/reports/` + `/reports_dev/` gitignored, plugin.json valid) and prints
  a unicode-bordered table with fix hints for any failures. Read-only —
  safe to run during any session, including paused or disarmed.
- `/janitor-compact-context` — agent-invocable self-compaction. Records a
  one-shot resume directive (`<project>/.janitor/state/resume-directive.txt` —
  "continue TRDD-xxxx at …", consumed once by the `PostCompact` hook) then fires
  a detached `/compact` at this session's own iTerm pane (matched by
  `$ITERM_SESSION_ID` UUID, strictly validated). SOFT by default: the command is
  typed without ESC, so it enqueues and runs when the current turn ends — no
  in-flight work is discarded. The agent invokes it when the
  context-watchdog's per-tool-call % injection crosses the threshold; after
  invoking, the agent ends its turn so `/compact` runs, then auto-resumes on the
  next heartbeat. iTerm-only for the trigger; elsewhere it records the directive
  and asks you to `/compact`. Backed by `scripts/compact_trigger.py`. Part of the
  context-compact watchdog (opt-in — see Hooks).
  - **`--hard`** — press ESC first, interrupting the in-flight turn so `/compact`
    runs NOW. For emergencies (context near the wall); the ≥85% enforcement hook
    requests this explicitly.
  - **`--handoff`** — run `/janitor-write-handoff` (a rich, agent-authored
    handoff) BEFORE `/compact`, for delicate junctures where the free mechanical
    PreCompact handoff isn't enough. Combinable with `--hard`.
- `/janitor-write-handoff` — writes a rich, agent-authored session handoff to
  `<project>/.janitor/state/agent-handoff.md` (the semantic layer — the plan, the
  next concrete action, the traps already hit) that COMPLEMENTS the always-on,
  zero-cost `pre-compact-handoff.py` mechanical handoff. Usually run by
  `/janitor-compact-context --handoff` (which passes `--then-compact`, so the skill
  chains to `/compact` when done); a bare `/janitor-write-handoff` writes the
  handoff and stops. Opt-in because authoring it costs tokens — reserve it for
  delicate junctures.
- `/janitor-reload-plugins` — agent-invocable `/reload-plugins --force` trigger
  (the analogue of `/janitor-compact-context` for reloads). Types a detached
  `/reload-plugins --force` at this session's own iTerm pane (same
  `$ITERM_SESSION_ID` UUID matching, strictly validated) so the running session
  picks up freshly auto-updated PLUGIN hooks/skills without the human typing the
  command — the working path for the heartbeat's `[janitor-reload]` marker, since
  the Skill tool refuses built-in slash commands. Records NO state (reloading does
  not discard the conversation). SOFT by default (no ESC — the reload enqueues and
  runs after the current turn finishes); **`--hard`** presses ESC first for an
  immediate reload. iTerm-only for the trigger; elsewhere it asks you to
  `/reload-plugins --force`. Backed by `scripts/reload_trigger.py`.
- `/janitor-reload-skills` — agent-invocable `/reload-skills` trigger, for
  STANDALONE (non-plugin) skills and commands installed at local / project / user
  scope. `/reload-plugins` reloads only plugin-bundled skills, so after adding a
  standalone skill/command you need `/reload-skills` instead — this skill types it
  into this session's own pane. SOFT by default (enqueue, no ESC); **`--hard`**
  presses ESC first. The
  machine-wide sibling is **`/janitor-global-reload-skills`** (reloads standalone
  skills across every running session). Backed by `scripts/reload_skills_trigger.py`.
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
  `bash $CLAUDE_PLUGIN_ROOT/scripts/safe_delete.py -- <path>...` for agents
  whose tool surface excludes Skill but includes Bash.
- `/janitor-supply-chain-watcher` — audits installed dependencies for
  newly-published HIGH/CRITICAL security advisories (Shai-Hulud-class
  npm/PyPI/pnpm worm patterns). Walks every lock file in the project
  (`package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `requirements.txt`,
  `uv.lock`, `poetry.lock`, `Cargo.lock`), queries both GitHub Security
  Advisories (via `gh api graphql`) and OSV.dev (via `curl`), matches
  advisory affected ranges against installed versions, and fails loud on
  any HIGH or CRITICAL overlap. Uses an advisory cursor cache at
  `$MAIN_ROOT/.janitor/state/sca-cursor.json` so subsequent runs only
  fetch advisories newer than the cursor — steady-state cost stays under
  12 API calls/hour. Findings land in
  `$MAIN_ROOT/reports/janitor-supply-chain-watcher/<TS>-findings.md`
  with the exact upgrade command per package.
- `/janitor-github-workflow-doctor` — audits `.github/workflows/*.yml` for
  security issues and emits surgical fix recipes. Runs zizmor (when present)
  then a native Python second pass (`scripts/doctor_classify.py`) covering
  the full Sentinel rule set — 32 GitHub-Actions checks across three tiers:
  a google-re2 RegexSet for single-line patterns (hardcoded secrets,
  IDE-config injection, curl-pipe-shell, unpinned images, …), a structural
  YAML walker for context/absence rules (shell- and github-script injection
  via a precise attacker-context allowlist, `pull_request_target` + fork
  checkout, missing permissions/timeouts, excessive permissions,
  build-publish-same-job, …), and a repo-level pass (missing-zizmor).
  Recipes in `skills/janitor-github-workflow-doctor/references/sentinel-rules-recipes.md`.
- `/janitor-github-workflow-create` — scaffolds hardened
  `.github/workflows/` from project shape (Python/Node/Rust/Go/plugin) with
  least-privilege `permissions:`, SHA-pinned actions,
  `persist-credentials: false`, `timeout-minutes`, and a zizmor job baked in.
- `/janitor-fork-pr-cache-audit` — detects the TanStack-class fork-PR
  cache-poisoning and `pull_request_target` checkout patterns (D1–D4) across
  every workflow; report-only, with cache-fencing recipes.
- `/janitor-dependabot-doctor` — scaffolds or audits `dependabot.yml` /
  `renovate.json` so the `github-actions` (and other) ecosystems get
  automated dependency-update PRs.
- `/janitor-credential-window-audit` — scans the repo, shell-env variable
  *names*, and CI config for the window during which credentials are live
  and reachable; reports findings without ever echoing secret values.

### Control commands (severity × scope)

Janitor activity is controlled along two axes — **severity** (how hard you
stop it) and **scope** (this project only, or the whole machine). The
quadrants:

| | Local (this project) | Global (daemon + all instances) |
|---|---|---|
| **Disarm** = true stop / teardown | `/janitor-disarm` ↔ `/janitor-arm` | `/janitor-global-disarm` ↔ `/janitor-global-arm` |
| **Maintenance** = keep firing, cache-refresh-only | `/janitor-maintenance-mode` ↔ `/janitor-maintenance-mode off` | `/janitor-maintenance-mode global` ↔ `/janitor-maintenance-mode global off` |

**DISARM tears down.** Locally it removes the heartbeat cron, so nothing
fires until you `/janitor-arm` again. Globally it sets the kill-switch — the
daemon **exits** on its next loop tick and removes its OS keepalive — and it
also stops every armed session's heartbeat: on the next fire `dispatch.py`
sees the stop flag and emits a bare `[janitor-self-disarm]` marker, so the
session runs `/janitor-disarm` and the cron **deletes itself**
(TRDD-RQ9FIFX6). `/janitor-global-arm` clears the switch; re-arm a session
with `/janitor-arm` and its next heartbeat lazy-spawns a fresh daemon.

**PAUSE IS GONE (v0.67.0).** It suspended the janitor while leaving the cron
firing and the daemon resident — from the outside, indistinguishable from a
healthy fleet, which is how a project sat silently disabled for two weeks. A
stop is now the kill-switch alone: loud, total, and observable, because the
cron is deleted. A stale `global-pause.flag` or `.janitor/state/paused` left by
an older version is INERT, and both are swept automatically.

**MAINTENANCE keeps firing — but cheap.** This is the middle ground between
full and disarm. Each fire does the MINIMUM: the turn re-reads the session
context at the 0.1× prompt-cache **read** rate (which resets the 5-minute cache
TTL), then `dispatch.py` emits a never-stop "keep going" continue-nudge and
returns — no detectors, no daemon spawn. It exists because letting the cache **die** (disarm → no fires) forces
the next real turn to **rewrite** the whole context at the 1.0× rate — ~10× a
cache read. So a maintenance fire costs ~1/10 of a cache-death rewrite: the
cheapest way to keep a session (and thus its whole project's cache) warm.
Maintenance **wins over** a global stop, so one session can stay warm while the
fleet stays down (the daemon idles its tasks and is not respawned). Use it for
idle-but-returning work; `/janitor-maintenance-mode off` restores full fires.

**The never-stop nudge is UNCONDITIONAL and has no off-switch.** Every due heartbeat, in every
mode, prints `[janitor-resume]` + "continue your pending task". It used to be opt-in with an
opt-out (`/janitor-keep-going` / `off`, plus a `keep_going_default` config knob); both were
removed in v0.67.0 because both were sticky and silent. A host was found carrying
`.janitor/state/keep-going-off` dated 14 days earlier: every heartbeat had fired, correctly done
nothing, and looked exactly like a healthy one — which is precisely the failure the nudge exists
to prevent. A guard you can switch off invisibly is not a guard.

**Rollout caveat.** The `[janitor-self-disarm]` marker is baked into the cron
prompt at arm time, so crons armed BEFORE this shipped won't self-disarm on
their own — run `/janitor-disarm` once in each such session (or `/janitor-arm`
to pick up the new prompt).

The global commands are backed by
`scripts/global_control_cli.py disarm|arm|pause|unpause|maintenance|maintenance-off|status`
(the `status` subcommand reports the daemon's current armed / paused / maintenance
state; maintenance takes precedence in the readout, mirroring dispatch's mode
resolution).

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

### Auto-renewal of the 7-day cron (silent since v0.5.2)

Recurring `CronCreate` jobs auto-expire after 7 days. dispatch.py
tracks the arm time in `.janitor/state/heartbeat-armed-at.ts`, and once the
cron is 6+ days old it emits a bare `[janitor-renew]` marker on stdout.
The cron prompt installed by `/janitor-arm` (since v0.5.2) teaches Claude
to **silently** run `/janitor-arm` on that marker WITHOUT echoing it — so
the renewal happens behind the scenes; you never see a "your cron is about
to expire" reminder. `/janitor-arm` is idempotent (it replaces the cron
with a fresh 7-day one and clears the renew-seen dedupe).

**Upgrade path (one-time):** existing crons armed with the pre-v0.5.2
prompt do NOT carry the silent-execute clause. After installing v0.5.2
you'll see the bare `[janitor-renew]` line ONCE per session — Claude still
acts on it (the token is documented), the cron is replaced with a fresh
new-prompt one, and from then on future renewals are silent forever. The
nudge threshold remains tunable via `heartbeat_renewal_threshold_days`.

## Installation

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

```text
/janitor-arm
```

This arms the heartbeat. The cron is **session-scoped** (Claude Code scheduled tasks
live in the current conversation and are restored only on `--resume`/`--continue`;
there is no parameter that outlives the session), so it does **not** survive a Claude
restart. You do not normally need to re-arm by hand: the SessionStart hook nudges
`/janitor-arm` on each new session, and a cron nearing the 7-day expiry emits
`[janitor-renew]`. Work that must genuinely outlive a session belongs to the global
daemon, not the cron.

On Claude Code v2.1.110+, `claude --resume <session-id>` and
`claude --continue` also resurrect unexpired scheduled tasks, so the
heartbeat survives explicit resume too. On older versions those commands
could leave the cron behind — re-run `/janitor-arm` if no drift lines
surface after an explicit resume.

## Usage

Day-to-day the janitor is hands-off: once `/janitor-arm` is run, the
heartbeat fires every ~5 minutes, runs the due [detectors](#detectors),
and surfaces one-line drift findings in the session — silence means
nothing drifted. Typical interactions:

- `/janitor-audit` — run a full on-demand audit instead of waiting for
  the heartbeat cadences.
- `/janitor-doctor` — deep-scan the repo's GitHub workflows
  (zizmor + Sentinel classifiers).
- `/janitor-safe-delete <path>` — move files to the recoverable
  `.trashcan/` instead of `rm`.
- `/janitor-autofix-on|off` — toggle the act-don't-ask remediation
  policy per project.

The full command list lives in [Skills](#skills); tuning knobs in
[Configuration](#configuration).

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
iterating `scripts/detectors/`, so `<detector>` above expands to every
detector script at HEAD (20 at v0.4.0; the dispatcher auto-discovers any
new ones added in future releases).

### Installed rules — lifecycle & cleanup

The SessionStart hook copies the plugin's shipped rules (`rules/*.md`) into the
active scope's rules dir — `~/.claude/rules/` (user install) or
`<project>/.claude/rules/` (project/local install) — because Claude Code's rule
loader only reads those, not a plugin's bundled `rules/`. The shipped set is
`commit-discipline`, `markdown-memory-recall`, `use-safe-delete`,
`janitor-heartbeat-protocol`, `janitor-footprint`, plus the three universal
governance rules `trdd-design-tasks`, `prrd-design-rules`, and
`universal-kanban` — the IND (ai-maestro-independent) half of ai-maestro's
3-pillars split, usable in any project with no server or plugin beyond the
janitor (their DEP overlays are installed separately by the ai-maestro server,
never by the janitor). The set is auto-discovered by globbing `rules/*.md`, so
dropping a new `.md` there ships it — there is no hardcoded list. Each installed
rule carries a **conditional inert-guard** at its top plus an
`ai-maestro-janitor:installed-rule` provenance marker:

- **Disarmed** (`/janitor-global-disarm` set the kill-switch) → the rule tells
  the agent to treat it as **inert** this session.
- **Uninstalled** (the plugin's data dir is gone) → the rule declares itself an
  **orphan** the plugin could not remove and asks the agent to surface it for
  deletion — while forbidding any memory deletion.

Because Claude Code has **no uninstall hook** and does **not** clean a plugin's
`~/.claude/rules/` on uninstall, the janitor removes its own orphaned rules two
ways, both **provenance-marker-gated** (a rule you wrote yourself is never
touched, and **no memory store is ever touched**): SessionStart strips janitor
rules from any scope it was uninstalled from (partial uninstall / redundant
project mirror), and the global daemon's `rules-cleanup` task removes user-scope
orphans once the plugin is fully uninstalled (it outlives the plugin on its
orphaned cache for ~7 days). Opt out with
`CLAUDE_PLUGIN_OPTION_RULES_CLEANUP_ENABLED=0`; tune the daemon cadence with
`CLAUDE_PLUGIN_OPTION_DAEMON_RULES_CLEANUP_INTERVAL` (default 3600 s).

### Wikimem and MEMORY.md — two memory systems that coexist

The janitor's curated **Wikimem** (`memory/wikimem/`, memgrep-indexed) and Claude
Code's own harness-owned `MEMORY.md` are separate, cooperating systems — `MEMORY.md`
is **not deprecated**. The janitor maintains exactly **one line** in it: a link to
the scope's main wikimem overview page — the bridge between the two. It verifies
that line is present, re-adds it if deleted, and otherwise never touches the file.
The `janitor-memory-harvest` chore mirrors newly-written `MEMORY.md` entries into
the wiki, additively, on its own cadence.

### Uninstalling — your memories are safe

The **USER-scope memory corpus** lives inside the plugin's persistent data dir
(`~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory/`), which
`claude plugin uninstall` deletes by default when removing the last scope. Two
things keep your memories from ever being lost:

- **A synced backup mirror at `~/.claude/ai-maestro-janitor-memory/`.** Every
  session start syncs the corpus there (additive — it never deletes a note). The
  mirror lives **outside** the data dir, so a plain uninstall leaves it intact; on
  your next install the memory is **restored from the mirror** automatically. You
  don't have to do anything.
- **`--keep-data` preserves the primary directly** — use it to keep the canonical
  store in place across an uninstall:

  ```bash
  claude plugin uninstall ai-maestro-janitor --keep-data
  ```

(The **LOCAL** `~/.claude/projects/<slug>/memory/` and **PROJECT**
`<repo>/.claude/project/memory/` stores live outside the data dir and survive
uninstall regardless.)

## Verified behaviour

End-to-end rate-limit recovery was validated on 2026-04-19 against a live
network outage (WiFi off for ~90 seconds, then back on):

1. In-flight turn failed during the outage → `StopFailure` hook wrote
   `.janitor/state/rate-limited.flag` and `rate-limited-since.ts`.
2. The heartbeat cron kept ticking inside Claude Code; the fires that
   landed during the outage were enqueued.
3. When the network came back, the next queued fire delivered. `dispatch.py`
   saw the flag, emitted
   `[janitor-resume] rate-limit cleared after 89s — API is reachable again.`,
   and cleared the flag.
4. Claude Code processed that line as a fresh user turn and resumed the
   previous pending task.

No bot, no polling loop, no supervisor wrapper — the session never died, only
the interrupted turn did. The three-component pattern — passive account
switcher, recurring cron, and idempotent state file read each fire —
is the design the plugin embodies: dispatch.py treats the flag file as the
single source of truth, so whether the turn that clears it runs 5 seconds or
5 hours after `StopFailure` wrote it, the user-facing effect is identical.

## Configuration

All knobs are `userConfig` entries in `plugin.json`. Set them at install time via
the `/plugin configure` interface, or edit **`~/.claude/settings.json`** (user
scope) directly.

> **Claude Code 2.1.207 changed where plugin options may live.** Option values
> (`pluginConfigs`) are **no longer read from a project-level
> `.claude/settings.json`** — only user, `--settings`, and managed settings are
> honored. This README used to tell you to edit the project file; that no longer
> does anything, and it fails **silently** — the knob simply reverts to its
> default with no error. If you configured the janitor before 2.1.207 and it has
> started behaving like a fresh install, move your `pluginConfigs` block from
> `<repo>/.claude/settings.json` to `~/.claude/settings.json`.
>
> User scope is the right home for the janitor anyway: it is a **user-scope
> plugin** guarding the whole machine (the daemon is a machine-wide singleton),
> and `/janitor-arm` refuses to arm a project/local-scope install.
>
> This restriction applies to `pluginConfigs` only. An **`env` block** in a
> project `.claude/settings.json` still works, so the daemon knobs documented
> above (`CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE`, …) can still be set there —
> though user scope is preferable for the same reason.

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
| `heartbeat_renewal_threshold_days` | 6 | Days after arming before dispatch.py emits a bare `[janitor-renew]` marker. Since v0.5.2 the cron prompt installed by `/janitor-arm` teaches Claude to silently run `/janitor-arm` on that marker — renewal is automatic + invisible. Existing crons armed with the pre-v0.5.2 prompt will surface the marker once before the first silent-prompt re-arm. |
| `version_check_interval` | 300 | Min seconds between checks against `api.github.com` for a newer plugin release. 5 min by default — runs every heartbeat. ~12 cheap GitHub requests/hour, well under both API limits (60/h unauth, 5000/h `gh`-auth). |
| `auto_update_on_new_release` | **true** (since v0.5.3) | When true, the global janitor daemon auto-runs `claude plugin marketplace update ai-maestro-plugins` + `claude plugin update ai-maestro-janitor@ai-maestro-plugins --scope <auto>` whenever a newer release is on GitHub, then sets the reload-needed flag so the next heartbeat emits `[janitor-reload]` and Claude silently runs `/reload-plugins`. The daemon's flock guarantees single-writer semantics (closes [issue #7](https://github.com/Emasoft/ai-maestro-janitor/issues/7)). When false, the version-update detector instead emits a manual-update nudge. |
| `daemon_enabled` | true | When true, per-session heartbeats lazy-spawn the global janitor daemon (`scripts/daemon.py`) on the `<global-state>` dir (canonically `${CLAUDE_PLUGIN_DATA}/global-state/` since TRDD-2U8AH82F), which owns every machine-global auto-update task (bulk marketplace refresh, user-scope plugin updates, janitor self-update). Singleton via exclusive flock — N sessions = ONE daemon. Manual kill switch: `touch <global-state>/kill-switch.flag` (running daemon exits on next loop tick). |
| `daemon_marketplace_refresh_interval` | 1200 | Min seconds the daemon waits between bulk `claude plugin marketplace update` runs (no args = every configured marketplace). 20 min by default. The daemon is the only writer of the GLOBAL refresh, so a moderate cadence is enough; narrower per-session refreshes of just the local+project plugins' marketplaces still run every 5 min via `marketplace_refresh_interval`. |
| `daemon_user_plugins_update_interval` | 3600 | Min seconds between full user-scope plugin sweeps. 1 h by default — a full sweep over ~80 plugins × ~5 s each takes ~7 min, so hourly keeps everything fresh without burning CPU. |
| `daemon_version_update_interval` | 21600 | Min seconds the daemon waits between janitor self-update checks. 6 h by default — GitHub releases land at human-day granularity so this is plenty. Each cycle reads the local cache's highest version, queries `gh api releases/latest`, and — when behind — runs `claude plugin update ai-maestro-janitor@ai-maestro-plugins --scope <auto>`. Gated additionally by `auto_update_on_new_release` (no-op when false). |
| `trashcan_purge_enabled` | true | When true, the trashcan-purge detector auto-removes safe-delete batches older than `trashcan_max_age_days`. Set false to disable. |
| `trashcan_max_age_days` | 90 | Days after which a safe-delete batch is auto-purged. Computed from the folder-name timestamp; mtimes inside the batch are ignored. |
| `trashcan_purge_interval` | 86400 | Min seconds between trashcan-purge passes. |
| `stash_stale_days` | 30 | Days a git stash can sit untouched before stale-stash flags it. |
| `stale_stash_interval` | 86400 | Min seconds between stale-stash scans. |
| `remote_credentials_interval` | 3600 | Min seconds between remote-credentials checks. The detector is cheap; the failure mode (credential leak) is severe enough to warrant a relatively fast cadence. |
| `nested_git_safety_interval` | 3600 | Min seconds between nested-`.git` scans. |
| `tracked_ignored_interval` | 3600 | Min seconds between tracked-ignored scans. (HEAD-cached: only re-runs when HEAD has moved since the last check.) |
| `log_retention_days` | 30 | Days of `.janitor/logs/<detector>.log` history to keep. Pruned at most once per UTC day at the top of `dispatch.py`. Set to `0` to disable retention. |
| `plugin_auto_update_enabled` | true | When true, `plugin-updates` runs `claude plugin update <id> --scope <scope>` automatically. When false, the detector only emits an informational drift line per available update — the user runs the command manually. |
| `plugin_auto_update_scopes` | `local,project` | Comma-separated subset of `{local, project}`. The janitor HARD-REFUSES to touch `user` or `managed` scopes regardless of this value. `project` = `.claude/settings.json` (committed, team-shared); `local` = `.claude/settings.local.json` (gitignored, your personal overrides for this project). |
| `plugin_auto_update_exclude` | `""` | Comma-separated `plugin@marketplace` IDs to skip entirely — useful to pin a specific plugin to its current version when a regression is suspected. |
| `plugin_updates_interval` | 300 | Min seconds between `plugin-updates` passes. 5 min by default — runs every heartbeat. The detector bails in <0.5s when there are no project-scoped plugins; when candidates exist, both the marketplace refresh and per-plugin update no-op when nothing has changed, so each heartbeat costs only a few cheap subprocess invocations. |
| `marketplace_refresh_interval` | 300 | Min seconds between scoped per-session marketplace refreshes. 5 min by default — runs every heartbeat. Refreshes ONLY the marketplaces hosting plugins enabled in `<project>/.claude/settings.json` and `<project>/.claude/settings.local.json` — never the global bulk refresh (that's `daemon_marketplace_refresh_interval`, 20 min). Detached worker, PID-deduped, sequential `claude plugin marketplace update <name>` per unique marketplace. Also keeps the daemon-staleness watchdog (drift line at most once per UTC hour when the daemon's last bulk refresh is older than 2× its cadence). |
| `user_plugins_update_interval` | 300 | Min seconds between user-scope plugin auto-update passes. 5 min by default — runs every heartbeat. Spawns a detached worker that runs `claude plugin update <id> --scope user` per user-scope plugin (enabled + disabled). The worker PID is tracked so overlapping fires skip. Track 1 of the auto-update directive — project-agnostic. |
| `local_plugins_update_interval` | 300 | Min seconds between local-scope plugin auto-update passes. 5 min by default — runs every heartbeat. Reads `.claude/settings.local.json`, filters to plugins with `enabled: true`, runs `claude plugin update <id> --scope local` per plugin via a detached worker. Track 2a of the auto-update directive — per-project, no git mutation (settings.local.json is gitignored). |
| `project_plugins_update_interval` | 300 | Min seconds between project-scope plugin auto-update passes. 5 min by default — runs every heartbeat. Reads `.claude/settings.json`, filters to plugins with `enabled: true`, runs `claude plugin update <id> --scope project` per plugin via a detached worker. On detected settings.json drift, emits a `[project-plugins-commit-needed]` drift line with the exact `git commit --only -- .claude/settings.json` command for Claude to execute — signing, pre-commit hooks, and branch protection rules are honored via the user's git config (no `--no-verify`, no signing detection, no flock coordination). Track 2b of the auto-update directive. |
| `mcp_config_drift_interval` | 3600 | Min seconds between `mcp-config-drift` passes. Cheap (just JSON parsing + a few `git check-ignore` calls), so a 1-hour cadence is well-affordable. |
| `settings_scope_drift_interval` | 3600 | Min seconds between `settings-scope-drift` passes. Two `git check-ignore` calls. |
| `subagent_scope_drift_interval` | 3600 | Min seconds between `subagent-scope-drift` passes. One `find` plus one `git check-ignore` per agent file. |
| `claude_md_scope_drift_interval` | 3600 | Min seconds between `claude-md-scope-drift` passes. Three `git check-ignore` calls. |
| `cross_scope_reference_drift_interval` | 3600 | Min seconds between `cross-scope-reference-drift` passes. A few `grep` per tracked source + one `git check-ignore` per resolved reference. |
| `workflow_security_enabled` | true | When true, the `workflow-security` detector scans `.github/workflows/` with the native Sentinel engine every heartbeat and surfaces CRITICAL/HIGH findings. READ-ONLY (never edits a workflow). Set false to disable heartbeat workflow scanning (the on-demand `/janitor-github-workflow-doctor` skill still works). |
| `workflow_security_interval` | 300 | Min seconds between `workflow-security` scans. 5 min by default — runs every heartbeat. Content-hashed: an unchanged-workflows fire costs only a few small file reads; a workflow edit forces a fresh scan so a newly-introduced injection or secret-leak surfaces within one cadence. |
| `branch_protection_enabled` | true | When true, the `branch-protection` detector asks the GitHub API (read-only) whether the default branch has classic protection OR an active ruleset, and surfaces an URGENT drift line only when it can DEFINITIVELY confirm neither. NEVER configures protection itself. Skips silently when `gh` is absent/unauthenticated, the viewer is not a repo admin, or any probe is indeterminate. Set false to disable. |
| `branch_protection_interval` | 21600 | Min seconds between `branch-protection` checks. 6 h by default — branch rulesets change rarely and each pass makes a few `gh` API calls. Nags once until fixed and re-arms automatically if protection is later removed. |
| `pkg_manager_min_release_age_minutes` | 7200 | Minimum age (minutes) the `pre-tool-pkg-guard` hook will accept for `pnpm config set minimumReleaseAge`, `minimum-release-age` in `.npmrc`, and `pnpm.minimumReleaseAge` in `package.json` / `pnpm-workspace.yaml`. 7200 ≈ 5 days, matches safedep's recommendation after the art-template compromise. |
| `pkg_manager_hook_allow_user_override` | false | When false (default), the `pre-tool-pkg-guard` hook hard-denies every detected bypass. When true, it downgrades to `ask` — per-call user confirmation instead of a block. Every block is logged regardless to `<global-state>/pkg-manager-guard.log`. |
| `pkg_manager_policy_enabled` | true | When true (default), the `package-manager-policy` detector scans the project's package-manager config for missing or weak safety knobs and flags when no install-time malware firewall is on PATH. |
| `pkg_manager_policy_interval` | 21600 | Min seconds between `package-manager-policy` scans. 6 h by default — package-manager config rarely changes, and the detector content-hashes the files anyway so an unchanged-config fire costs only file stats. |
| `context_watchdog_enabled` | true | When true (DEFAULT), the `pre-tool-context-usage` `PreToolUse` hook fires on EVERY tool call and guards the per-turn context-size token bleed (every turn re-reads the WHOLE context, so a session near the 1M cap burns ~its size per turn). It reads the live occupancy from the statusline snapshot, or falls back to the transcript's latest assistant input+cache occupancy over `context_window_tokens`. Two-tiered. ADVISORY (at/above `context_compact_suggest_pct`, default 60): a `/janitor-compact-context` nudge via `additionalContext` with no `permissionDecision`, so the tool flow is untouched. ENFORCEMENT (at/above `context_hardstop_pct`, default 85, gated by `context_autocompact_enabled`): queues the compaction itself and DENIES the tool call so the turn ends cleanly for `/compact`, then `post-compact-resume` continues at a reduced context. Fail-open everywhere (no terminal or any error degrades to the advisory, never a stuck deny). DEFAULT-ON because the bleed it prevents cost a month of tokens; set false to disable both tiers, or `context_autocompact_enabled=false` to keep only the advisory. |
| `context_compact_suggest_pct` | 60 | Context-window usage % at/above which the watchdog's `PreToolUse` hook appends a suggestion to run `/janitor-compact-context`. Default 60 leaves ~40% headroom so `/compact` can still run (wait too long — e.g. to ~999k on the 1M window — and `/compact` itself fails). Only consulted when `context_watchdog_enabled` is true. This is the soft WARN level; the hard ENFORCE level is `context_hardstop_pct`. |
| `context_hardstop_pct` | 85 | Context-window % at/above which the ENFORCEMENT tier queues a compaction on this pane and DENIES the tool call so the turn ends cleanly for `/compact` (then `post-compact-resume` continues at reduced context). 85 is high enough to be rare, low enough that `/compact` still succeeds. Gated by `context_autocompact_enabled`; fires at most once per episode (180s dedupe) and ONLY when a compaction can actually be queued (iTerm/tmux); otherwise it degrades to the advisory, never a stuck deny. Set 0 to disable enforcement by threshold. |
| `context_autocompact_enabled` | true | When true (default), the ENFORCEMENT tier is active (auto-compact + deny at/above `context_hardstop_pct`). When false, the guard is advisory-only: it still nudges at `context_compact_suggest_pct` but NEVER denies a tool call. Set false to never let the guard interrupt a turn. |
| `context_window_tokens` | 1000000 | The window size used to compute the usage % from the TRANSCRIPT fallback (no statusline snapshot). Default 1000000. Ignored when the statusline snapshot is present (it carries the real window). Set to your model's window if you run a non-1M context and rely on the transcript fallback. |

## Weekly fallback

The heartbeat only fires while a Claude Code session is open. For coverage
during week-long gaps, this plugin ships a GitHub Actions workflow at
`.github/workflows/weekly-audit.yml` that runs the same drift checks every
Monday at 09:00 UTC and opens a GitHub issue if anything is found.

## Prerequisites

- Claude Code v2.1.98 or later (`CronCreate` / `CronDelete` / `CronList`).
- `gh` CLI authenticated (`gh auth login`).
- A git repo with an `origin` remote pointing at GitHub.

### Recent Claude Code fixes the janitor benefits from

These are CC-side improvements that affect janitor reliability without
any plugin-side change — staying on a recent CC build is recommended:

- **v2.1.136** fixed plugin `Stop` / `UserPromptSubmit` hooks failing
  when CC's plugin cache cleanup deleted a plugin version still in use
  by a running session. Before this fix, a long-running janitor session
  that survived a CC autoupdate could silently lose its
  `on-stop-failure.py` rate-limit capture — the very signal that drives
  resume-from-rate-limit. From v2.1.136 onward, the hooks survive the
  cache GC.
- **v2.1.133** fixed a bug where subagents in OTHER plugins could not
  discover the janitor's skills (e.g. `/janitor-safe-delete`) through
  the `Skill` tool. Subagents now see plugin skills regardless of which
  plugin they belong to.
- **v2.1.139** added a hook `args: string[]` exec form that spawns
  hook commands directly without a shell, removing the need to quote
  path placeholders like `${CLAUDE_PLUGIN_ROOT}`. The janitor still
  ships the legacy `command:` shell form to preserve the ≥ v2.1.98
  floor; if your `${CLAUDE_PLUGIN_ROOT}` resolves to a path with
  spaces and you are on v2.1.139+, you can convert each hook in
  `hooks/hooks.json` from `command: "uv run --script ..."` to
  `args: ["uv", "run", "--script", ...]` locally — both forms read
  the same plugin code.
- **v2.1.142** hardened two failure modes the heartbeat
  depends on. First, plugin cache cleanup no longer deletes the
  *active* plugin version directory when install metadata is
  missing — `/janitor-arm` bakes the running version's absolute
  `dispatch.py` path into the cron prompt, so deleting that
  directory would break every later heartbeat fire; this extends
  the v2.1.136 cache-GC protection above. Second, the background
  daemon now detects system clock jumps across macOS sleep/wake
  instead of counting them as elapsed idle time, so a laptop
  closed overnight no longer drops background sessions on wake.
- **v2.1.143** added plugin dependency enforcement: `claude plugin
  disable` now refuses when another enabled plugin depends on the
  target (with a copy-pasteable disable-chain hint), and `claude
  plugin enable` force-enables transitive dependencies. The
  janitor's auto-update detectors (`marketplace-refresh`,
  `user-plugins-update`, `local-plugins-update`,
  `project-plugins-update`) drive **`claude plugin update`**, which
  only refreshes cached versions and never invokes
  enable/disable — so bulk auto-updates pass through the new guard
  cleanly. The implication is for *manual* disable steps in your
  own workflow: if you `claude plugin disable` a plugin the janitor
  depends on (e.g. `ai-maestro-plugin` for inter-agent messaging),
  the new refusal will tell you which dependents to disable first.
  v2.1.143 also dropped CC's internal `rm -rf` fallback when its
  own worktree cleanup hits an error — uncommitted scratch in
  CC-spawned worktrees is now safe. This does *not* change the
  janitor's `worktree-janitor` detector advice (it suggests
  `git worktree remove --force` on user-owned stale worktrees,
  which is independent of CC's internal cleanup path).
- **v2.1.144** capped the side-channel "is api.anthropic.com
  reachable" probe at 15s — previously a captive portal / firewall /
  VPN block could hang CC startup for up to 75s. Because the
  heartbeat fires every 5 minutes, a 60s startup tax on every fire
  would cripple the rate-limit recovery loop; v2.1.144 keeps the loop
  responsive on flaky networks. v2.1.144 also fixed completed/stopped
  background sessions briefly failing to wake being marked as
  permanent startup crashes — the rate-limit recovery directive
  depends on a paused session resuming cleanly, and the previous
  misclassification could lose work. Finally, session titles now come
  from the user's first prompt instead of plugin-monitor output —
  the janitor IS a plugin-monitor, so before this fix a session that
  opened on a `[janitor-heartbeat]` fire would get titled "janitor
  heartbeat" instead of whatever the user actually asked about.
- **v2.1.145** added `session_crons` (and `background_tasks`) to
  the `Stop` and `SubagentStop` hook input payloads. The janitor's
  `on-stop` / `on-stop-failure` hooks previously could not introspect
  the registered cron set without re-scanning
  `.claude/scheduled_tasks.json` by hand — now the list arrives
  inline. This unlocks future rate-limit-class diagnostics ("which
  cron last fired? when is the next one due?") without a filesystem
  round-trip on every stop. v2.1.145 also closed a permission-prompt
  bypass where bare variable assignments to non-allowlisted env vars
  in Bash commands were auto-approved — relevant because some
  janitor hooks set `CLAUDE_PROJECT_DIR=...` inline. Finally, `claude
  plugin validate` now flags `skills:` entries that point at a file
  instead of a directory (the janitor's
  `.claude-plugin/plugin.json` declares skill directories
  correctly — this is forward-looking insurance for any future skill
  refactor that touches the manifest shape).

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
- **Token cost feels high**: run `/janitor-token-report` to see per-turn
  output/input + cache-creation, mean/p50/p95/max, and spike flags — the cost
  driver is almost always long agent replies, not detection. Raise
  `heartbeat_cron` to `*/10 * * * *` or longer (cache-keepalive becomes
  best-effort past the 5-min TTL), and/or `/janitor-disarm` when you don't need
  the heartbeat (it then truly stops firing, costing zero).
- **Real-time token-spike + cache-miss guard** (default-ON, TRDD-KI24GR5Z): a
  PreToolUse hook watches the in-progress turn and nudges you to stop when it
  spikes. It fires on **output** (long replies) AND **cache-miss cache writes**
  (`cache_creation`, billed ~1.25× — the cheap 0.1× cache re-read is not counted).
  All configurable via `CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_*`:
  `ENABLED` (default on; set `false` to silence), advisory budgets `TURN_OUTPUT`
  (10000) / `TURN_CACHE_CREATION` (25000), hard budgets `TURN_OUTPUT_HARD`
  (40000) / `TURN_CACHE_CREATION_HARD` (75000), and `ENFORCE` (default off) which,
  when on, DENIES a new `Task`/`Agent` subagent spawn at the hard tier — the
  strongest cap, since subagents are the biggest token multiplier. Any budget of
  0 disables that signal.
- **Adaptive token-usage anomaly detector** (default-on, TRDD-EDSFEQ5C): the
  SLOW, pattern-based companion to the per-turn guard. Each heartbeat it reads
  `token-meter.jsonl`, learns a **robust** per-5-min baseline (median + MAD —
  never mean/stddev, because the log is heavy-tailed and bursty: measured, the
  top 10% of 5-min buckets held ~61% of all tokens), and alarms only on a
  **sudden outlier** — a bucket clearing `max(p99-floor, robust-z band,
  median×ratio)`, so a normal agent-spawn burst does not false-alarm but a real
  runaway does. Per-bucket deduped, disable-able via
  `CLAUDE_PLUGIN_OPTION_TOKEN_ANOMALY_ENABLED=false` (also `…_Z`, `…_FLOOR_PCT`,
  `…_BUCKET_SECONDS`).
- **`/janitor-token-report` window view**: alongside the per-fire distribution it
  now shows the rolling **5h and 7d** weighted-token sums + per-minute rate, the
  **busiest 5h/7d window ever observed** (an empirical *lower bound* on the
  account's real cap), and the per-5-min baseline. Pass `--util5h`/`--util7d`
  (the live utilization% from `/api/oauth/usage`) to turn those into an
  **estimated absolute cap** (`spent ÷ util%`) + minutes-to-exhaustion at the
  recent rate — the answer to "what is the max Opus tokens allowed in a 5h/7d
  window, and am I about to blow through it early".
- **Burn-rate alarm + fleet attribution** (`window-burn-rate` detector +
  `/janitor-token-attribution`): a window should reach 100% exactly at its reset
  if spent evenly, so `burn_ratio = util% ÷ (100 × elapsed-fraction)`. The
  heartbeat reads each account's live 5h/7d utilization% + reset boundary
  **READ-ONLY** through the OAuth rotator and, when a window burns **≥ 1.5×** its
  even pace (default; heading for an early rate-limit), emits one drift line —
  per account, min-util floored so a fresh window never nags. Because the account
  util% is aggregate across ~10 parallel projects, a trip also names the
  **top-consuming project** (its 5h share, its spike vs its own baseline, and
  where the spike came from) so the advice points at *who* to throttle.
  `/janitor-token-attribution` prints that fleet ranking on demand; `--live`
  gains a per-account burn line. Read-only, fail-open (a rotator/network hiccup
  is silent), opt-out `CLAUDE_PLUGIN_OPTION_WINDOW_BURN_ENABLED=false` (also
  `…_RATIO`, `…_MIN_UTIL`).

- **Throttled usage probe** (`scripts/lib/usage_probe.py`, TRDD-WEBA1RMF) — every
  read of `/api/oauth/usage` (the rotator's rotation decisions, `window-burn-rate`,
  `/janitor-token-report --live`) goes through **one throttled writer**. That
  endpoint requires a `claude-code/*` User-Agent — anything else lands in an
  aggressive rate-limit bucket that 429s persistently — and its 429s *worsen*
  under retry, because knocking again re-arms the server-side lockout instead of
  letting the token's usage bucket drain. That matters beyond politeness: the
  rotator reads a probe 429 as *"this account is MAXED"*, so a throttle makes the
  live account **and** every alternate look unusable at once and rotation stalls
  exactly when it is needed. The probe therefore sends the installed CLI's
  version as its UA, caches per account (the cache file's mtime **is** the TTL
  clock), honours `Retry-After` / `anthropic-ratelimit-*-reset` and otherwise
  backs off exponentially, and serialises concurrent refreshes with a
  non-blocking lock so the loser serves cache rather than firing a duplicate.
  It never raises and never resolves a credential itself — the rotator's
  cross-platform ladder (macOS Keychain → `.credentials.json` → GNOME Keyring)
  keeps owning that, so a telemetry probe can never raise a keychain dialog.
  Throttling design adapted from [ccgauge](https://github.com/pizzimenti/ccgauge)
  (MIT). Knobs: `CLAUDE_PLUGIN_OPTION_USAGE_PROBE_TTL_SECONDS` (600),
  `…_BACKOFF_BASE_SECONDS` (600), `…_BACKOFF_CAP_SECONDS` (7200),
  `…_STALE_SECONDS` (1800), `…_TIMEOUT_SECONDS` (6).

## License

MIT. See [LICENSE](./LICENSE).
