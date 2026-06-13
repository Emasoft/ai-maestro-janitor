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

**Platform:** macOS, Linux, and Windows (everywhere `uv` runs). Required:
[`uv`](https://docs.astral.sh/uv/) (every script is a `uv run --script`
PEP 723 file with `requires-python = ">=3.10"`), `git`, and `gh` (for the
detectors that talk to GitHub). No `bash`-specific syntax left in the hot
path; the only remaining shell wrapper is the cron back-compat shim.

## How it works

One durable recurring cron is armed on session start via the `/janitor-arm`
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
exclusive flock on `~/.claude/janitor-global-state/daemon.flock`, so N
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

| State file | Purpose |
| --- | --- |
| `~/.claude/janitor-global-state/daemon.flock` | exclusive flock held for the daemon's lifetime; the kernel releases it on death |
| `~/.claude/janitor-global-state/daemon.pid` | the live daemon's PID (diagnostic) |
| `~/.claude/janitor-global-state/daemon.heartbeat.ts` | tick written every loop iteration + during long workloads; sessions treat the daemon as stuck when this is older than `DEFAULT_DAEMON_STALE_SECONDS` (1800 s) |
| `~/.claude/janitor-global-state/marketplace-refresh.last-run.ts` | last successful bulk-refresh completion stamp |
| `~/.claude/janitor-global-state/user-plugins-update.last-run.ts` | same, for the user-scope plugin sweep |
| `~/.claude/janitor-global-state/version-update.last-run.ts` | same, for the janitor self-update task |
| `~/.claude/janitor-global-state/reload-needed.flag` | written by the daemon when a real plugin update lands; the next heartbeat emits `[janitor-reload]` and clears the flag |
| `~/.claude/janitor-global-state/daemon.log` | daemon's own log (rotated by `state.rotate_log_if_big`) |
| `~/.claude/janitor-global-state/kill-switch.flag` | touch to make the running daemon exit on its next loop tick |

**Manual control:**
- Inspect: `cat ~/.claude/janitor-global-state/daemon.log | tail -30`
- Disable temporarily: `touch ~/.claude/janitor-global-state/kill-switch.flag`
- Re-enable: `rm ~/.claude/janitor-global-state/kill-switch.flag` (the next
  heartbeat lazy-spawns a fresh daemon)
- Disable permanently: set `daemon_enabled: false` in userConfig
- Kill (graceful): `kill $(cat ~/.claude/janitor-global-state/daemon.pid)`

The daemon NEVER touches per-project plugin state (`local-plugins-update`,
`project-plugins-update`, `plugin-updates` remain per-session) and NEVER
modifies your repos — it only operates on `~/.claude/plugins/`.

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
  `~/.claude/janitor-global-state/pkg-manager-guard.log`.

  Sample deny reason: `[pkg-manager-guard] pnpm --no-frozen-lockfile
  permits lockfile drift (use a real lockfile update + commit). Set
  CLAUDE_PLUGIN_OPTION_PKG_MANAGER_HOOK_ALLOW_USER_OVERRIDE=true to confirm
  per call, or raise CLAUDE_PLUGIN_OPTION_PKG_MANAGER_MIN_RELEASE_AGE_MINUTES
  if the threshold is wrong.`
- **Context-compact watchdog** — `PreToolUse` `pre-tool-context-usage.py` +
  `PostCompact` `post-compact-resume.py` (OPT-IN; `context_watchdog_enabled =
  true`). Claude Code's native auto-compact is unreliable on the 1M window —
  sessions run past the threshold, sometimes to ~999k where `/compact` itself
  can no longer run (forcing a total-loss `/clear`). The watchdog puts the
  agent in the loop instead, as a four-stage cycle:
  - **Producer** — your statusline writes the live context % to a project-local
    `<project>/.claude/janitor/context-usage.<session>.json` (throttled ≤ 1/10 s).
  - **Consumer** — `pre-tool-context-usage` (`PreToolUse`, all tools) reads that
    snapshot and injects `Context window: NN% …` into the agent's context before
    every tool call. Advisory only — emits **no `permissionDecision`**, so the
    tool's normal permission flow is untouched. At/above `context_compact_suggest_pct`
    (default 60) it appends a nudge to run `/janitor-compact-context`.
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
  expiry; while present, dispatch.py exits silently. Lighter than
  `/janitor-disarm` — use when starting a focus block or large refactor.
  `/janitor-resume` lifts the pause; if a duration was supplied
  (`/janitor-pause 2h`, `/janitor-pause until 18:00`), the next heartbeat
  after expiry auto-clears the sentinel.
- `/janitor-resume` — removes the paused sentinel. Idempotent (no-op when
  not paused). Does NOT arm the cron — for that, use `/janitor-arm`.
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
  a detached ESC→`/compact` at this session's own iTerm pane (matched by
  `$ITERM_SESSION_ID` UUID, strictly validated). The agent invokes it when the
  context-watchdog's per-tool-call % injection crosses the threshold; after
  invoking, the agent ends its turn so `/compact` runs, then auto-resumes on the
  next heartbeat. iTerm-only for the trigger; elsewhere it records the directive
  and asks you to `/compact`. Backed by `scripts/compact_trigger.py`. Part of the
  context-compact watchdog (opt-in — see Hooks).
- `/janitor-reload-plugins` — agent-invocable `/reload-plugins` trigger (the
  analogue of `/janitor-compact-context` for reloads). Fires a detached
  ESC→`/reload-plugins` at this session's own iTerm pane (same `$ITERM_SESSION_ID`
  UUID matching, strictly validated) so the running session picks up freshly
  auto-updated plugin hooks/skills without the human typing the command — the
  working path for the heartbeat's `[janitor-reload]` marker, since the Skill
  tool refuses built-in slash commands. Records NO state (reloading does not
  discard the conversation). iTerm-only for the trigger; elsewhere it asks you to
  `/reload-plugins`. Backed by `scripts/reload_trigger.py`.
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

Durable recurring `CronCreate` jobs auto-expire after 7 days. dispatch.py
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

This arms the durable heartbeat. Because `durable: true` is set, the cron
survives session restarts — you do not need to re-arm on each launch unless
the 7-day recurring-cron expiry has hit.

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
- `/janitor-pause` · `/janitor-resume` — temporarily silence / restore
  the heartbeat; `/janitor-disarm` removes the cron entirely.
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

## Verified behaviour

End-to-end rate-limit recovery was validated on 2026-04-19 against a live
network outage (WiFi off for ~90 seconds, then back on):

1. In-flight turn failed during the outage → `StopFailure` hook wrote
   `.janitor/state/rate-limited.flag` and `rate-limited-since.ts`.
2. The durable heartbeat cron kept ticking inside Claude Code; the fires that
   landed during the outage were enqueued.
3. When the network came back, the next queued fire delivered. `dispatch.py`
   saw the flag, emitted
   `[janitor-resume] rate-limit cleared after 89s — API is reachable again.`,
   and cleared the flag.
4. Claude Code processed that line as a fresh user turn and resumed the
   previous pending task.

No bot, no polling loop, no supervisor wrapper — the session never died, only
the interrupted turn did. The three-component pattern — passive account
switcher, durable recurring cron, and idempotent state file read each fire —
is the design the plugin embodies: dispatch.py treats the flag file as the
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
| `heartbeat_renewal_threshold_days` | 6 | Days after arming before dispatch.py emits a bare `[janitor-renew]` marker. Since v0.5.2 the cron prompt installed by `/janitor-arm` teaches Claude to silently run `/janitor-arm` on that marker — renewal is automatic + invisible. Existing crons armed with the pre-v0.5.2 prompt will surface the marker once before the first silent-prompt re-arm. |
| `version_check_interval` | 300 | Min seconds between checks against `api.github.com` for a newer plugin release. 5 min by default — runs every heartbeat. ~12 cheap GitHub requests/hour, well under both API limits (60/h unauth, 5000/h `gh`-auth). |
| `auto_update_on_new_release` | **true** (since v0.5.3) | When true, the global janitor daemon auto-runs `claude plugin marketplace update ai-maestro-plugins` + `claude plugin update ai-maestro-janitor@ai-maestro-plugins --scope <auto>` whenever a newer release is on GitHub, then sets the reload-needed flag so the next heartbeat emits `[janitor-reload]` and Claude silently runs `/reload-plugins`. The daemon's flock guarantees single-writer semantics (closes [issue #7](https://github.com/Emasoft/ai-maestro-janitor/issues/7)). When false, the version-update detector instead emits a manual-update nudge. |
| `daemon_enabled` | true | When true, per-session heartbeats lazy-spawn the global janitor daemon (`scripts/daemon.py`) on `~/.claude/janitor-global-state/`, which owns every machine-global auto-update task (bulk marketplace refresh, user-scope plugin updates, janitor self-update). Singleton via exclusive flock — N sessions = ONE daemon. Manual kill switch: `touch ~/.claude/janitor-global-state/kill-switch.flag` (running daemon exits on next loop tick). |
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
| `pkg_manager_hook_allow_user_override` | false | When false (default), the `pre-tool-pkg-guard` hook hard-denies every detected bypass. When true, it downgrades to `ask` — per-call user confirmation instead of a block. Every block is logged regardless to `~/.claude/janitor-global-state/pkg-manager-guard.log`. |
| `pkg_manager_policy_enabled` | true | When true (default), the `package-manager-policy` detector scans the project's package-manager config for missing or weak safety knobs and flags when no install-time malware firewall is on PATH. |
| `pkg_manager_policy_interval` | 21600 | Min seconds between `package-manager-policy` scans. 6 h by default — package-manager config rarely changes, and the detector content-hashes the files anyway so an unchanged-config fire costs only file stats. |
| `context_watchdog_enabled` | false | When true, the `pre-tool-context-usage` `PreToolUse` hook fires on EVERY tool call and injects the live context-window % (read from the statusline's project-local `context-usage.<session>.json` snapshot) via `additionalContext` — advisory only, never altering the tool's permission flow. At/above `context_compact_suggest_pct` it nudges the agent to run `/janitor-compact-context`. OPT-IN (off) because it fires on every tool call. The trigger leg of the context-compact watchdog; pairs with the `post-compact-resume` `PostCompact` hook + the `/janitor-compact-context` skill for an auto-resuming compaction loop for unattended overnight work. |
| `context_compact_suggest_pct` | 60 | Context-window usage % at/above which the watchdog's `PreToolUse` hook appends a suggestion to run `/janitor-compact-context`. Default 60 leaves ~40% headroom so `/compact` can still run (wait too long — e.g. to ~999k on the 1M window — and `/compact` itself fails). Only consulted when `context_watchdog_enabled` is true. |

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
- **v2.1.142** hardened two failure modes the durable heartbeat
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
  VPN block could hang CC startup for up to 75s. Because the durable
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
- **Token cost feels high**: raise `heartbeat_cron` to `*/10 * * * *` or
  longer. Accept that cache-keepalive becomes best-effort past the 5-min TTL.

## License

MIT. See [LICENSE](./LICENSE).
