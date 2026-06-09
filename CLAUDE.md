# ai-maestro-janitor — project structure & architecture reference

> **Purpose of this file:** a compact map so a session can recall how the
> janitor works WITHOUT re-reading the tree. Keep it current when structure
> changes. Verified-detail for the core wiring; grouped lists + conventions
> for the breadth (37 detectors, ~200 pattern libs).

## What it is

A Claude Code plugin that keeps the dev environment tidy & secure. Two tiers:

1. **Per-session heartbeat** — a durable `CronCreate` per project fires a fresh
   turn every ~5 min → runs **project-scoped** drift detectors `--one-shot` →
   emits one-line "drift" findings to the model. Silent when nothing drifts.
2. **Global daemon** — ONE machine-wide singleton process that owns every
   **user/global-scope** mutation (so N sessions don't stampede the same
   command — issue #7). Spawned lazily by any session's heartbeat.

## Scope invariant (HARD RULE — issue #7)

- **user/global-scope ops → daemon ONLY.** Bulk `claude plugin marketplace
  update` (argless), `claude plugin update --scope user`, janitor self-update.
- **project/local-scope ops → per-session detectors.** They hard-filter
  `scope in (user, managed)` and only ever pass a specific `<market>` arg.
- Cheap idempotent **file** writes to user-scope (rules) stay per-session but
  MUST be **atomic** (tmp + `os.replace`) — the file analogue of the daemon's
  single-writer lock for expensive commands.

## Filesystem & state conventions (per plugins-reference.md)

| Path | Resolves to | Lifecycle | Use for |
|---|---|---|---|
| `${CLAUDE_PLUGIN_ROOT}` | `~/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/<version>/` | **Ephemeral** — changes every update, GC'd ~7d | scripts, skills, hooks. **NEVER write state here.** |
| `${CLAUDE_PLUGIN_DATA}` | `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/` | **Persistent** — survives updates, backed up, purged only on uninstall | ALL persistent state, caches, venvs. **Prefer this.** |
| `$CLAUDE_PROJECT_DIR/.janitor/state/` | per-project | per-project | per-session detector state |

**Current state locations (and the migration TODO):**
- ✅ `dispatcher-stub.py` → `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py` (correct).
- ✅ per-session → `$PROJECT/.janitor/state/` (correct — project-scoped).
- ⚠️ **daemon global state → `~/.claude/janitor-global-state/`** (`global_state.py::global_state_dir`) — this is an UNOFFICIAL folder: not backed up, orphaned by purge, not version-preserved. **TODO: migrate to `${CLAUDE_PLUGIN_DATA}`.** Risk: the flock path changes → must migrate the *running* daemon carefully (move state + one-time dual-read) or two daemons race. Not a flip-the-switch change.

> **Principle (per user):** prefer `${CLAUDE_PLUGIN_DATA}` over any new
> `~/.claude/<custom>/` folder. The data dir is the only one guaranteed
> preserved across plugin/marketplace/version changes, backed up by backup
> tools, and cleanly purged on uninstall. Unofficial folders are lost by
> backups AND left as orphan junk by purge.

## Runtime / installed tree

```
~/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/<ver>/  ephemeral plugin (scripts/skills/hooks)
~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/         DATA: dispatcher-stub.py  (← daemon state SHOULD move here)
~/.claude/janitor-global-state/                                       UNOFFICIAL daemon state (migrate → DATA):
    daemon.pid · daemon.flock · daemon.heartbeat.ts · daemon.spawn-attempt.ts
    marketplace-op.lock (NEW) · {marketplace-refresh,user-plugins-update,version-update}.last-run.ts
    kill-switch.flag · reload-needed.flag
$PROJECT/.janitor/state/                                              per-session: last-run-<detector>.ts ·
    rate-limited.flag · rate-limited-since.ts · resume-after-compact.flag · resume-after-compact.ts ·
    resume-directive.txt (agent pointer) · heartbeat-armed-at.ts · heartbeat-renew-seen.txt · <detector> seen-files
cron: one durable CronCreate per project → fires the stub
```

## Control flow

**Heartbeat (per session):** cron prompt → `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py`
(re-resolves latest cached `<ver>/scripts/dispatch.py`, `os.execv`s into it — so
plugin updates auto-roll with NO re-arm) → `dispatch.py`:
1. `rate-limited.flag` present → emit `[janitor-resume]`, clear flag (also clears the compact-resume flag).
2. `resume-after-compact.flag` present → emit `[janitor-resume] …continue TRDD-xxxx…`, clear flag (post-compact auto-resume; the PostCompact hook wrote it — TRDD-31095269).
3. cron near 7-day expiry → emit `[janitor-renew]` (Claude re-runs /janitor-arm).
4. `ensure_daemon_running()` (lazy-spawn the singleton if dead).
5. daemon stale/old-version → request restart (auto-roll the daemon too).
6. run each **due** detector `--one-shot`; emit only NEW findings (seen-file dedupe).
7. `reload-needed.flag` → emit `[janitor-reload]` (Claude runs /reload-plugins).

**Daemon loop (`daemon.py`):** acquire singleton flock (else exit) → every tick,
run each due `Task`; `_run_workload` runs subprocess with **1800s cap** +
periodic heartbeat ticks. `Task.run()` stamps `<name>.last-run.ts`
**unconditionally** in `finally` (so stale last-run = task not *running*, not
failing-silently). Tasks: `marketplace-refresh` (1200s, bulk), `user-plugins-update`
(3600s, `--scope user`), `version-update` (21600s, self-update + sets reload-flag).
All marketplace updates wrap `gs.marketplace_lock()` (skip-if-held).

## Core files (verified)

**Top-level `scripts/`**
- `dispatcher-stub.py` — auto-roll stub in DATA; zero-arg, execs latest `dispatch.py`.
- `dispatch.py` — per-session heartbeat entry; detector roster + cadences; resume/renew/reload markers.
- `daemon.py` — global singleton daemon; `_run_workload`, `Task`/`Task.run` (finally-stamps last-run), `task_marketplace_refresh` / `task_user_plugins_update` / `task_version_update`, `_build_tasks`.
- `doctor_classify.py` + `commands/doctor.py` — GitHub workflow-doctor CLI (zizmor + Sentinel classifiers).
- `publish.py` — 14-gate fail-fast release pipeline (version bump → validate → lint → tests → commit → push → tag → GH release).
- `safe_delete.py` — moves targets to `.trashcan/` (the `/janitor-safe-delete` backend).
- `guard/branch_protection_apply.py` — applies branch-protection rules.

**`scripts/lib/` core (non-pattern)**
- `state.py` — per-session helpers (port of state.sh): `project_root`, `state_dir`(=`$PROJECT/.janitor/state`), `log_dir`, `atomic_write`, `log_line`, `read_int_state`, `is_truthy_env`, `coerce_int`.
- `global_state.py` — daemon contract: `global_state_dir` (⚠️ unofficial path), singleton flock (`acquire/release_singleton_flock`), **`marketplace_lock`/`acquire/release_marketplace_lock`** (cross-process serialization), daemon lifecycle (`daemon_pid`, `write/read_heartbeat`, `kill_switch_present`, `daemon_is_alive`, `ensure_daemon_running`, `spawn_daemon_detached`, `daemon_needs_restart`, `set/clear_reload_flag`).
- `dedupe.py` — `emit_once` (content-hash dedupe → unchanged findings stay silent).
- `version_update_lib.py` — janitor self-update helpers (`attempt_auto_update`, `do_auto_update_if_needed`, `detect_install_scopes`); daemon-only caller.
- `rules_installer.py` — `install_rules` copies plugin `rules/*.md` into the active scope's `.claude/rules/` (atomic tmp+replace; size-based idempotency). Called by `on-session-start`.
- others: `branch_protection_lib`, `git_utils`, `git_ops_patterns`, `posture`/`posture_modes`, `suppression`, `output_formats`, `security_helpers`, `ioc_taxonomy`, `janitor_self_integrity`, `zizmor_classifier`/`zizmor_patterns*`, `sentinel/` (workflow-doctor rule engine: `model`, `rules_absence/context/injection/extra/repo`).

## Conventions (breadth — list, don't per-symbol-dump)

**Detectors (`scripts/detectors/`, 37)** — each a standalone `--one-shot` script
run by `dispatch.py`; emits drift lines; slow ones use a PID-tracked detached-worker
that skips if the prior worker is alive; per-detector cadence + seen-file dedupe.
**Project-scoped — never touch user-scope.** Groups:
- *git/workflow hygiene:* pr-reconciler, worktree-janitor, dirty-tree, tracked-ignored, nested-git-safety, branch-protection, stale-stash, task-pr-mismatch, stale-task.
- *TRDD/task:* trdd-drift, trdd-reminder.
- *cleanup:* screenshot-purge, trashcan-purge.
- *scope drift:* settings-scope-drift, claude-md-scope-drift, cross-scope-reference-drift, subagent-scope-drift, mcp-config-drift.
- *supply-chain/security:* mcp-rugpull, remote-credentials, supply-chain-fingerprints, typosquat-watcher, provenance-audit, repo-trust-score, package-manager-policy, workflow-security, historical-cache-scan, binary-magic-scanner, ai-context-poisoning, subagent-report, janitor-self-integrity.
- *updates (some daemon-delegating shims):* marketplace-refresh, plugin-updates, local-plugins-update, project-plugins-update, **user-plugins-update (shim → daemon)**, version-update (shim → daemon).

**Pattern libraries (`scripts/lib/*_patterns.py`, ~200)** — the security knowledge
base. One module per attack class, uniform shape: exposes regex/rule definitions +
metadata consumed by the scanner detectors. Naming: `<domain>_patterns.py` (e.g.
`cloud_credential_patterns`, `prompt_injection_patterns`, `npm_lifecycle_patterns`,
`k8s_admission_patterns`, …). **Don't enumerate — grep by domain when needed.**

**Hooks (`scripts/hooks/`, 12)** — `on-session-start` (installs rules + ensures
daemon), `on-session-start-trdd-state`, `on-prompt-submit`, `on-stop`,
`on-stop-failure`, `post-edit-safety`, `post-mcp-response-sanitizer`,
`pre-bash-safety`, `pre-tool-pkg-guard`, `pre-tool-context-usage` (OPT-IN
PreToolUse → injects live context % on every tool call, suggests
/janitor-compact-context ≥60%), `post-compact-resume` (PostCompact → writes
`resume-after-compact.flag` so the next heartbeat emits `[janitor-resume]
…continue TRDD-xxxx…`; closes the watchdog loop so a compact doesn't stall an
unattended session — TRDD-31095269), `on-prompt-submit-user-mem` (UserPromptSubmit
→ the PRIVATE user-memory subsystem, TRDD-4334aad0). The context-watchdog trio
(pre-tool-context-usage + post-compact-resume + the `janitor-compact-context`
skill + `scripts/compact_trigger.py`) is OPT-IN via
`CLAUDE_PLUGIN_OPTION_CONTEXT_WATCHDOG_ENABLED`.

**USER-MEMORY subsystem (`commands/{to,search,share}-user-mem.md` +
`scripts/hooks/on-prompt-submit-user-mem.py` + `scripts/lib/user_mem_lib.py`,
TRDD-4334aad0)** — a PRIVATE, agent-invisible user-authored memory store at
`~/.claude/projects/<slug>/memory/user-mem/` (sibling of the agent corpus), with
an immutable monotonic counter (`.counter` + flock; numbers retired-never-reused).
`/to-user-mem [<text>]` saves (bare → previous user message via transcript);
`/search-user-mem <q>` searches ONLY that store via `memgrep find <q> <dir>
--use-index` (the `+`/`-`/wildcard/phrase DSL lives in the Rust crate);
`/share-user-mem <N>` is the ONE gate that injects a memory into context. PRIVACY
(verified vs the Claude Code hook docs): the UserPromptSubmit hook returns
`decision:block` (erases the prompt → save text + search query never reach the
model) and surfaces confirmations/results via `systemMessage` (user-only);
`/share-user-mem` is the sole path using `additionalContext` (which DOES reach
the model). Fast no-op for any non-user-mem prompt; never crashes the session.

**Skills (`skills/`)** — `janitor-arm` (install stub + arm cron; + `janitor-disarm`),
`janitor-supply-chain-watcher`, `janitor-dependabot-doctor`,
`janitor-credential-window-audit`, `janitor-github-workflow-doctor`,
`janitor-github-workflow-create`, `janitor-fork-pr-cache-audit`,
`janitor-compact-context` (agent-invocable self-compact + auto-resume; backed by
`scripts/compact_trigger.py`).

**Tests (`tests/`)** — pytest; one `test_*_patterns.py` per pattern lib + core tests
(`test_marketplace_lock`, `test_rules_installer`, `test_marketplace_refresh_daemon_stale`, …).
Real, no mocks; isolate global state via `JANITOR_GLOBAL_STATE_DIR` and `HOME`/`CLAUDE_PROJECT_DIR`.

**Design docs (`design/tasks/`)** — TRDDs (see `~/.claude/rules/trdd-design-tasks.md`).
