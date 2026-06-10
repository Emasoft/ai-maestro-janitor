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

<+-+-JANITOR-REPO-MAP-START-(do-not-modify)-+-+> v1 sha=de133a4cc62c digest=395e3b5e4334 generated=2026-06-11T01:09:39+0200
## Project map (auto-generated — do not edit between the fences)
`scripts/commands/doctor.py` — /janitor-doctor backing script — Python port of doctor.sh.
  · main() -> int
`scripts/compact_trigger.py` — Backing script for /janitor-compact-context (TRDD-31095269).
  · main() -> int
`scripts/daemon.py` — Global janitor daemon — single-instance owner of machine-global auto-update tasks.
  · task_marketplace_refresh() -> None — Run `claude plugin marketplace update` (bulk → all marketplaces).
  · task_user_plugins_update() -> None — Enumerate user-scope plugins and update each sequentially.
  · task_version_update() -> None — Auto-update the janitor plugin itself when GitHub is ahead of the
  · task_oauth_rotator_supervisor() -> None — Governance (alert-only) for the opt-in OAuth account rotator
  · task_oauth_rotator_tick() -> None — 60 s OAuth-rotator beat (TRDD-32acd15f), folded into the daemon per
  · Task — One periodic unit of work owned by the daemon.
  · Task.time_until_due(self) -> int
  · Task.is_due(self) -> bool
  · Task.run(self) -> None
  · main() -> int
`scripts/detectors/ai-context-poisoning.py` — AI-context-poisoning detector — npm + pip postinstall write audit.
  · main() -> int
`scripts/detectors/binary-magic-scanner.py` — binary-magic-scanner — magic-byte sniff for binaries in unexpected paths.
  · main() -> int
`scripts/detectors/branch-protection.py` — Branch-protection detector — flags an unprotected default branch.
  · main() -> int
`scripts/detectors/claude-md-scope-drift.py` — CLAUDE.md scope drift — Python port of claude-md-scope-drift.sh.
  · main() -> int
`scripts/detectors/cross-scope-reference-drift.py` — Cross-scope reference drift — Python port of cross-scope-reference-drift.sh.
  · main() -> int
`scripts/detectors/dirty-tree.py` — Dirty-tree detector — Python port of dirty-tree.sh.
  · main() -> int
`scripts/detectors/historical-cache-scan.py` — historical-cache-scan — known-malicious package version detector.
  · main() -> int
`scripts/detectors/janitor-self-integrity.py` — janitor-self-integrity — heartbeat self-attestation detector.
  · main() -> int
`scripts/detectors/local-plugins-update.py` — Local-plugins-update detector — Track 2a of the auto-update directive.
  · main() -> int
`scripts/detectors/marketplace-refresh.py` — Per-session marketplace refresh — scoped to local + project plugin marketplaces.
  · main() -> int
`scripts/detectors/mcp-config-drift.py` — MCP config drift — Python port of mcp-config-drift.sh.
  · main() -> int
`scripts/detectors/mcp-rugpull.py` — MCP rug-pull detector — fingerprint-drift audit on installed MCP servers.
  · main() -> int
`scripts/detectors/memory-librarian.py` — memory-librarian — SURFACE (never mutate) memory aggregation/conflict candidates.
  · NoteMeta — Parsed metadata for one memory note (from `memgrep index --markdown`).
  · ScopeReport — Everything the librarian surfaces for ONE memory scope root.
  · ScopeReport.has_findings(self) -> bool — True iff this scope surfaces ANYTHING (candidate or integrity issue).
  · main() -> int
`scripts/detectors/memory-scope-leak.py` — memory-scope-leak — keep the PUSHED memory scope free of machine/user-private data.
  · main() -> int
`scripts/detectors/nested-git-safety.py` — Nested-git-safety detector — Python port of nested-git-safety.sh.
  · main() -> int
`scripts/detectors/oauth-cookie-reminder.py` — OAuth-cookie refresh reminder (opt-in) — surfacing half of the OAuth-rotator
  · main() -> int
`scripts/detectors/oauth-login-needed.py` — OAuth one-time-login nudge (opt-in) — the reactive sibling of
  · slot_needs_login(has_refresh, token_days, has_session_key, grace_days) -> bool — PURE: does this account need a ONE-TIME human login?
  · slot_capture_stalled(has_refresh, has_session_key) -> bool — PURE (B3): is this account LOGGED IN but its OAuth capture has NOT completed?
  · main() -> int
`scripts/detectors/package-manager-policy.py` — Package-manager-policy detector — supply-chain hardening audit.
  · main() -> int
`scripts/detectors/plugin-updates.py` — Plugin-updates detector — Python port of plugin-updates.sh.
  · main() -> int
`scripts/detectors/pr-reconciler.py` — PR reconciler — Python port of pr-reconciler.sh.
  · main() -> int
`scripts/detectors/project-plugins-update.py` — Project-plugins-update detector — Track 2b of the auto-update directive.
  · main() -> int
`scripts/detectors/provenance-audit.py` — provenance-audit — heartbeat-cadenced provenance / SBOM audit.
  · main() -> int
`scripts/detectors/remote-credentials.py` — Remote-credentials detector — Python port of remote-credentials.sh.
  · main() -> int
`scripts/detectors/repo-trust-score.py` — repo-trust-score — dropper-pattern audit on the current project tree.
  · main() -> int
`scripts/detectors/report-to-trdd-drift.py` — report-to-trdd-drift — nudge when a DECISION report has no TRDD.
  · main() -> int
`scripts/detectors/screenshot-purge.py` — screenshot-purge — Age- and disk-pressure-based purge of UI test screenshots.
  · main() -> int
`scripts/detectors/settings-scope-drift.py` — Settings-scope drift — Python port of settings-scope-drift.sh.
  · main() -> int
`scripts/detectors/stale-stash.py` — Stale-stash detector — Python port of stale-stash.sh.
  · main() -> int
`scripts/detectors/stale-task.py` — Stale task detector — Python port of stale-task.sh.
  · main() -> int
`scripts/detectors/subagent-report.py` — Subagent report detector — Python port of subagent-report.sh.
  · main() -> int
`scripts/detectors/subagent-scope-drift.py` — Subagent-scope drift — Python port of subagent-scope-drift.sh.
  · main() -> int
`scripts/detectors/supply-chain-fingerprints.py` — supply-chain-fingerprints — heartbeat detector for high-signal supply-chain
  · main() -> int
`scripts/detectors/task-pr-mismatch.py` — Task/PR mismatch detector — Python port of task-pr-mismatch.sh.
  · main() -> int
`scripts/detectors/tracked-ignored.py` — Tracked-ignored detector — Python port of tracked-ignored.sh.
  · main() -> int
`scripts/detectors/trashcan-purge.py` — trashcan-purge — Python port of trashcan-purge.sh.
  · main() -> int
`scripts/detectors/trdd-drift.py` — TRDD drift detector — Python port of trdd-drift.sh.
  · main() -> int
`scripts/detectors/trdd-reminder.py` — TRDD reminder — Python port of trdd-reminder.sh.
  · main() -> int
`scripts/detectors/typosquat-watcher.py` — Typosquat-watcher — heartbeat detector for typo-squat dependency names.
  · main() -> int
`scripts/detectors/user-plugins-update.py` — Per-session shim — user-scope plugin updates are owned by the global daemon.
  · main() -> int
`scripts/detectors/version-update.py` — Version-update detector — read-only after TRDD-be2efa56 §9 follow-up.
  · main() -> int
`scripts/detectors/workflow-security.py` — Workflow-security detector — heartbeat-cadenced GitHub Actions audit.
  · main() -> int
`scripts/detectors/worktree-janitor.py` — Worktree janitor — Python port of worktree-janitor.sh.
  · main() -> int
`scripts/dispatch.py` — Cron-fire entry point for the janitor heartbeat — Python port of dispatch.sh.
  · main() -> int
`scripts/dispatcher-stub.py` — ai-maestro-janitor cron dispatcher stub — auto-rolling dispatcher.
  · main() -> int
`scripts/doctor_classify.py` — Doctor's second-pass workflow classifier — CLI driver.
  · main() -> int
`scripts/guard/branch_protection_apply.py` — Tier 2 GUARDED AUTO-REMEDIATION — branch-protection baseline applier.
  · main() -> int
`scripts/hooks/on-prompt-submit-autorecall.py` — UserPromptSubmit hook — OPT-IN automatic memory recall (issue #16, item 2).
  · main() -> int
`scripts/hooks/on-prompt-submit-user-mem.py` — UserPromptSubmit hook — the PRIVATE user-memory commands (TRDD-4334aad0).
  · main() -> int
`scripts/hooks/on-prompt-submit.py` — UserPromptSubmit hook — host-level user-presence breadcrumb (TRDD-fb4850b5).
  · main() -> int
`scripts/hooks/on-session-start-trdd-state.py` — SessionStart hook — actively surface in-progress TRDD STATE blocks on resume.
  · main() -> int
`scripts/hooks/on-session-start.py` — SessionStart hook — Python port of on-session-start.sh.
  · main() -> int
`scripts/hooks/on-stop-failure.py` — StopFailure hook — Python port of on-stop-failure.sh.
  · main() -> int
`scripts/hooks/on-stop.py` — Stop hook — Python port of on-stop.sh.
  · main() -> int
`scripts/hooks/post-compact-resume.py` — PostCompact hook — record what the next heartbeat should auto-resume.
  · main() -> int
`scripts/hooks/post-edit-memory-correction.py` — PostToolUse hook — memory correction-protocol advisory (TRDD-c77dae09, rank 5).
  · main() -> int
`scripts/hooks/post-edit-safety.py` — PostToolUse hook — assistant-being-conned write detector.
  · main() -> int
`scripts/hooks/post-mcp-response-sanitizer.py` — PostToolUse hook — MCP-response prompt-injection sanitiser.
  · main() -> int
`scripts/hooks/pre-bash-safety.py` — PreToolUse hook — compositional bash-exfil + sensitive-write blocker.
  · check_compositional_exfil(command) -> str | None — Return a deny-reason if the command is a source+sink exfil chain.
  · check_sensitive_write(command) -> str | None — Return a deny-reason if the command writes to a sensitive path.
  · main() -> int
`scripts/hooks/pre-tool-context-usage.py` — PreToolUse hook — surface the live context-window % to the agent on every tool call.
  · main() -> int
`scripts/hooks/pre-tool-pkg-guard.py` — PreToolUse guard against package-manager safety-knob bypasses.
  · check_bash(command) -> str | None
  · check_edit(tool, tool_input, cwd) -> str | None
  · main() -> int
`scripts/lib/__init__.py` — Marker file. Makes scripts/lib/ an importable Python package so hooks
`scripts/lib/ai_context_extras.py` — AI-context extras — net-new rules from deep-ai-context wave.
  · Finding — A single rule match. Shape-compatible with
  · Rule — A rule with a pre-compiled pattern. Used by the single-regex
  · mask_markdown_code_blocks(text) -> str — Replace fenced + inline code with same-length spaces so byte
  · find_install_typosquats(text) -> list[Finding] — Return one Finding per install command that targets a likely
  · find_undisclosed_capabilities(prose_text, source_files) -> list[Finding] — Compute ``actual_apis - declared_apis``.
  · find_base64_instruction_payloads(text) -> list[Finding] — Return one Finding per base64 blob whose decoded payload contains
  · find_install_import_correlations(prose_text, python_files, declared_deps) -> list[Finding] — Cross-reference install commands and imports.
  · scan_text(text) -> list[Finding] — Run every single-regex rule against ``text`` (prose; the caller is
`scripts/lib/branch_protection_lib.py` — Branch-protection ruleset helpers — shared between the Tier 1 user-invoked
  · baseline_ruleset_payloads(default_branch, required_status_checks) -> list[dict] — Return the three ratified baseline ruleset payloads (branch pair + tag protection).
  · detect_repo_slug(plugin_root) -> str | None — Read `repository` from `.claude-plugin/plugin.json` and return
  · gh_available() -> bool
  · detect_default_branch(slug) -> str | None — Ask gh for the repo's default branch. Returns None on failure.
  · viewer_is_admin(slug) -> bool — Best-effort: True iff the authenticated viewer has admin perms
  · list_existing_rulesets(slug) -> list[dict] | None — Return the ruleset list for `slug`, or None on failure.
  · ruleset_id_by_name(slug, name) -> int | None — Return the numeric id of the ruleset named `name`, or None.
  · baselines_present(slug) -> bool | None — True iff ALL THREE ratified rulesets are already attached to the repo.
  · detect_required_status_checks(project_root) -> list[dict] — Discover the repo's CI check contexts from its WORKFLOW FILES.
  · delete_ruleset_by_name(slug, name) -> tuple[bool, str] — Delete the ruleset named `name` if present. Returns (success, msg).
  · apply_baseline_rulesets(slug, default_branch, project_root) -> tuple[bool, list[tuple[str, bool, str]], list[dict]] — Apply ALL THREE ratified rulesets idempotent-by-name (branch pair +
  · guard_mode_enabled() -> bool — Master gate for the Tier 2 auto path. Default is False — the
`scripts/lib/daemon_watchdog.py` — Shared daemon-task staleness watchdog for the per-session detector shims.
  · emit_if_daemon_stale(*, task_name, last_run_filename, cadence_env, default_cadence_s, subject) -> None — Print a once/hour drift line iff `task_name`'s completion stamp is stale
`scripts/lib/dedupe.py` — Dedupe helper — Python port of scripts/lib/dedupe.sh.
  · emit_once(seen_file, key, message) -> Optional[str] — Return `message` the FIRST time `key` is seen, None on repeats.
  · emit_forget(seen_file, key) -> None — Forget a key so the next occurrence re-emits.
`scripts/lib/git_utils.py` — Shared git helpers — Python port of scripts/lib/git-utils.sh.
  · is_squash_merged(branch_ref, base_ref, cwd) -> bool — Detect whether <branch_ref> was squash-merged into <base_ref>.
  · scope_tracking_status(rel) -> str — Probe git tracking status of `rel` (relative to project root).
`scripts/lib/global_state.py` — Shared contract for the GLOBAL janitor daemon — system-wide singleton that
  · global_state_dir() -> Path — Return the system-wide janitor state directory.
  · init_global_state() -> Path — Create the global state dir if missing. Idempotent. Return its path.
  · daemon_pid() -> Optional[int] — Read daemon.pid → int, or None if missing / malformed.
  · write_daemon_pid(pid) -> None
  · remove_daemon_pid() -> None
  · write_heartbeat(now) -> None
  · read_heartbeat() -> int
  · kill_switch_present() -> bool
  · daemon_is_alive(max_silence_s) -> bool — True iff the daemon's PID is alive AND its heartbeat is recent.
  · acquire_singleton_flock() -> Optional[int] — Acquire the exclusive non-blocking flock on daemon.flock.
  · release_singleton_flock(fd) -> None — Close the fd; the kernel releases the flock as a side effect.
  · acquire_marketplace_lock() -> Optional[int] — Non-blocking exclusive flock on marketplace-op.lock.
  · release_marketplace_lock(fd) -> None — Release the marketplace-op flock and close the fd. Best-effort.
  · marketplace_lock() -> Iterator[bool] — Serialise a `claude plugin marketplace update` against every other process.
  · acquire_oauth_rotator_lock() -> Optional[int] — Non-blocking exclusive flock on oauth-rotator-tick.lock.
  · release_oauth_rotator_lock(fd) -> None — Release the oauth-rotator-tick flock and close the fd. Best-effort.
  · oauth_rotator_lock() -> Iterator[bool] — Serialise an OAuth-rotator tick against every other tick-class process.
  · daemon_script_path() -> Path — Resolve scripts/daemon.py absolute path.
  · spawn_daemon_detached() -> Optional[int] — Spawn the daemon as a fully-detached child. Return child PID or None.
  · reload_flag_present() -> bool
  · set_reload_flag(reason) -> None — Mark that a `/reload-plugins` is needed before the next user turn.
  · clear_reload_flag() -> None
  · daemon_needs_restart() -> bool — True iff the running daemon's script path doesn't match the current cache.
  · request_daemon_restart() -> bool — Send SIGTERM to a stale daemon so the next heartbeat lazy-spawns a new one.
  · ensure_daemon_running(max_silence_s) -> bool — If the daemon is dead AND not kill-switched AND enabled, spawn it.
`scripts/lib/ioc_taxonomy.py` — IOC taxonomy primitives — distilled from the deep-forensics-ioc audit
  · IOCTaxonomyError — Raised when an IOC bundle cannot be parsed.
  · IOCRecord — Per-threat IOC bundle — the four-quadrant breakdown distilled from
  · incident_response_advisory(stage) -> str — Return the canonical advisory string for an IR stage.
  · parse_ioc_yaml(path) -> list[IOCRecord] — Load a per-threat IOC bundle (or a list of bundles) from `path`.
`scripts/lib/janitor_integrity.py` — File-integrity primitives for the resilient daemon (TRDD-7100178d, Pillar 2).
  · sha256_bytes(data) -> str — Hex sha256 of ``data``.
  · atomic_write_bytes(path, data, *, mode) -> None — Write ``data`` to ``path`` atomically: a uniquely-named tmp file in the SAME
  · backup_and_write(path, data, *, mode) -> None — Critical write with a REDUNDANT MIRROR. ``data`` is written to BOTH the primary
  · read_or_restore(path) -> bytes | None — Read ``path`` with corruption recovery.
  · backup_is_consistent(path) -> bool — True iff ``path`` has a fully-established, self-consistent redundant mirror: the
`scripts/lib/janitor_self_integrity.py` — Janitor self-integrity primitives — deterministic, stdlib-only.
  · has_integrity_notice(text) -> bool — True iff `text` contains the canonical integrity-notice block.
  · load_or_create_key(data_dir) -> bytes | None — Return the 32-byte integrity key, generating one on first call.
  · compute_finding_hmac(*, rule_id, severity, path, line_number, message, corpus_hash, key) -> str | None — Compute a base32-12 HMAC tag for a single drift line.
  · wrap_drift_line(raw_line, *, rule_id, severity, path, line_number, corpus_hash, key) -> str — Append `[hmac=...]` to `raw_line`, or return it unchanged.
  · verify_drift_line(line, *, rule_id, severity, path, line_number, corpus_hash, key) -> bool — Verify a drift line previously wrapped by `wrap_drift_line`.
  · AuditChain — Append-only HMAC-SHA256 chained NDJSON log.
  · AuditChain.append(self, event) -> dict — Append `event` (a dict of caller-supplied fields).
  · AuditChain.verify(self) -> tuple[bool, int, str] — Verify every entry in the chain, top to bottom.
  · compute_manifest(plugin_root, globs) -> dict[str, str] — Compute `{ relative_path: sha256-hex }` over the matched files.
  · write_manifest(manifest, path) -> None — Write the manifest atomically.
  · load_manifest(path) -> dict[str, str] — Load a manifest written by `write_manifest`.
  · verify_manifest(plugin_root, manifest_path, globs) -> tuple[list[str], list[str], list[str]] — Compare live files against the manifest baseline.
`scripts/lib/output_formats.py` — Output formats — HMAC-signed scan badge, approval-gate protocol, FP-filters DSL.
  · make_badge(report_id, verdict, scanned_at, key, expiry_days) -> str — Build a signed badge token.
  · verify_badge(badge, key, *, now) -> tuple[bool, str] — Verify a signed badge token.
  · format_security_triggered(action, normalized_diff) -> str — Build the canonical SECURITY-TRIGGERED gate block.
  · parse_approval_response(reply) -> bool — Return True iff the reply is EXACTLY ``APPROVED`` after .strip().
  · apply_fp_filters(text, filters) -> bool — Return True iff ``text`` contains ANY substring from ``filters``.
`scripts/lib/posture.py` — Posture-grade computation for the janitor heartbeat.
  · PostureGrade — A single grade snapshot for the heartbeat.
  · compute(critical, high, major, minor, mal_advisories) -> PostureGrade — Compute a posture grade from per-severity counts + OSV MAL-* count.
  · should_surface_today(stamp_file) -> bool — Return True iff today's local date has not yet been stamped.
  · mark_surfaced_today(stamp_file) -> None — Stamp today's date so should_surface_today returns False for
  · format_drift_line(grade) -> str — Render the grade as a single heartbeat-friendly drift line.
`scripts/lib/posture_modes.py` — Three-mode posture matrix supplementing scripts/lib/posture.py.
  · PostureMode — One row of the 3-mode posture matrix.
  · default_mode() -> PostureMode — Return the janitor's default posture mode.
  · select_mode(name) -> PostureMode — Look up a `PostureMode` by its canonical kebab-case name.
  · apply_mode_to_grade(grade, mode) — Return a new PostureGrade with the letter shifted by the mode.
  · compliance_map(rule_id) -> dict[str, list[str]] — Return the compliance framework cross-walk for a janitor rule_id.
`scripts/lib/repomap/__init__.py` — Auto-maintained project-map extractor/renderer (TRDD-e247a349).
`scripts/lib/repomap/extractor.py` — Project-map extractor — language-agnostic interface + Python adapter.
  · Symbol — One public symbol in a file.
  · FileMap — Extracted structure of one source file.
  · extract_python(path) -> FileMap — Extract a FileMap from a Python source file via stdlib `ast`.
`scripts/lib/repomap/markers.py` — Marker-fence operations for the project-map block (TRDD-e247a349 §3, §4).
  · MalformedFences — The CLAUDE.md text contains a broken JANITOR-REPO-MAP fence pair
  · has_map_block(text) -> bool — True iff a well-formed fenced block is present. Malformed fences raise
  · read_fence_header(text) -> dict[str, str] | None — Parse the START fence's metadata (`sha`, `digest`, `generated`, schema)
  · replace_map_block(text, new_block) -> str — Swap the existing fenced block for `new_block` (the maintainer's
  · insert_map_block(text, new_block) -> str — First-time insertion (the /janitor-auto-repomap-on path): append the
  · remove_map_block(text) -> str — Splice out the fenced block entirely (the /janitor-auto-repomap-off
`scripts/lib/repomap/renderer.py` — Project-map renderer — FileMaps → the fenced CLAUDE.md block (TRDD-e247a349 §2).
  · render_body(filemaps) -> str — Deterministic map body (no fences, no timestamp). Individual files first
  · structure_hash(filemaps) -> str — 12-hex sha256 over the rendered body. Identical structure → identical
  · render_block(filemaps, *, generated_iso, digest) -> str — The full fenced block ready to splice into CLAUDE.md. `digest` is the
`scripts/lib/rules_installer.py` — Install plugin-shipped rule files into the active scope's .claude/rules/.
  · install_rules(plugin_root) -> list[str] — Copy <plugin_root>/rules/*.md to every active scope's rules dir.
`scripts/lib/security_helpers.py` — Shared security primitives — distilled from 10-agent study of 141
  · shannon_entropy(s) -> float — Shannon entropy in bits per character.
  · looks_like_base64(s, *, min_len) -> bool — True iff `s` looks like a base64-encoded blob worth decoding.
  · try_decode_base64(s) -> Optional[bytes] — Best-effort base64 decode. Returns None on any failure.
  · is_known_config_loader(name, ecosystem) -> bool — True iff `name` is a known config / env loader for `ecosystem`.
  · levenshtein(a, b) -> int — Iterative DP Levenshtein distance. O(len(a)*len(b)) time, O(len(b))
  · popular_npm_packages() -> frozenset[str]
  · popular_pypi_packages() -> frozenset[str]
  · is_typosquat_candidate(name, popular, *, max_distance) -> Optional[str] — If `name` is within `max_distance` edits of any popular target
  · agent_context_files() -> frozenset[str]
  · is_agent_context_path(path) -> bool — True iff `path` (basename or relative path) matches an
  · owasp_id_label(asi_id) -> str — Return the human label for an OWASP Agentic Top-10 id.
  · has_invisible_unicode(s) -> bool — True iff `s` contains any zero-width, bidi-override, or other
  · strip_invisible_unicode(s) -> str — Return `s` with every invisible-Unicode character removed.
  · find_authority_impersonation(text) -> list[str] — Return every match of an authority-impersonation pattern in `text`.
  · nfkc_diff(text) -> str — Return the NFKC-normalised form of `text` IFF it differs from the
  · wrap_with_advisory_armor(message) -> str — Prefix a finding message with the self-defending advisory boilerplate
`scripts/lib/sentinel/__init__.py` — Sentinel structural-rule tier for the janitor workflow auditor.
`scripts/lib/sentinel/model.py` — Shared contract for the Sentinel structural rule tier.
  · Workflow — Parsed GitHub Actions workflow with raw-line + structured access.
  · Workflow.triggers(self)
  · Workflow.jobs(self) -> dict
  · Workflow.steps(self, job) -> list
  · Workflow.permissions(self, scope, job)
  · Workflow.line_of(self, pattern) -> Optional[int]
  · Workflow.lines_of(self, pattern) -> list
  · Workflow.line_content(self, num) -> Optional[str]
  · Workflow.uses_actions(self) -> list — List of {uses, step, line} for every step with a `uses:` key.
  · safe_trigger_only(wf) -> bool
  · guarded_by_safe_event(wf, line_num) -> bool
  · in_run_block(wf, target_line) -> bool — True iff target_line sits inside a `run:` block (port of shell_injection_expr).
  · in_github_script_block(wf, target_line) -> bool — True iff target_line sits inside an actions/github-script `script:` block.
  · Rule — Base for structural rules. Subclasses set name/severity/description and
  · Rule.check(self, wf) -> list
`scripts/lib/sentinel/rules_absence.py` — Sentinel structural rules — "absence / context" tier.
  · MissingPermissions — Missing-permissions rule with FP-hardening round 3 two-state
  · MissingPermissions.check(self, wf) -> list[Finding]
  · MissingTimeouts
  · MissingTimeouts.check(self, wf) -> list[Finding]
  · ExcessivePermissions
  · ExcessivePermissions.check(self, wf) -> list[Finding]
  · MissingPersistCredentials
  · MissingPersistCredentials.check(self, wf) -> list[Finding]
  · MissingEnvProtection
  · MissingEnvProtection.check(self, wf) -> list[Finding]
  · OverlyBroadTriggers
  · OverlyBroadTriggers.check(self, wf) -> list[Finding]
  · MissingFrozenLockfile
  · MissingFrozenLockfile.check(self, wf) -> list[Finding]
`scripts/lib/sentinel/rules_context.py` — Context-tier Sentinel rules: ones whose detection needs job/step/trigger
  · StaticAwsCredentials
  · StaticAwsCredentials.check(self, wf) -> list
  · UnscopedAppToken
  · UnscopedAppToken.check(self, wf) -> list
  · DockerBuildArgSecrets
  · DockerBuildArgSecrets.check(self, wf) -> list
  · UnpinnedArtifact
  · UnpinnedArtifact.check(self, wf) -> list
  · SelfHostedRunnerFork
  · SelfHostedRunnerFork.check(self, wf) -> list
  · BuildPublishSameJob
  · BuildPublishSameJob.check(self, wf) -> list
  · AllowForksArtifact
  · AllowForksArtifact.check(self, wf) -> list
  · DangerousLifecycleScripts
  · DangerousLifecycleScripts.check(self, wf) -> list
  · IfAlwaysTrue — Step / job `if:` condition that always evaluates to true.
  · IfAlwaysTrue.check(self, wf) -> list
  · AiConfigInjection — Attacker-controllable expression interpolated into an AI-tool config.
  · AiConfigInjection.check(self, wf) -> list
  · ArtipackedUpload — actions/upload-artifact in a fork-trusted-trigger workflow.
  · ArtipackedUpload.check(self, wf) -> list
  · CachePoisoningPrTrigger — `actions/cache` step in a workflow with a fork-trusted trigger.
  · CachePoisoningPrTrigger.check(self, wf) -> list
`scripts/lib/sentinel/rules_extra.py` — Extended Sentinel structural rules — net-new detectors beyond the Wave 14
  · WorkflowRunPwnCheckout — `workflow_run` trigger + checkout of the triggering workflow's head.
  · WorkflowRunPwnCheckout.check(self, wf) -> list
  · MatrixStrategyInjection — Matrix value populated from `github.event.*` AND consumed in `run:`.
  · MatrixStrategyInjection.check(self, wf) -> list
  · GithubAppSkipTokenRevoke — `actions/create-github-app-token` with revocation suppressed.
  · GithubAppSkipTokenRevoke.check(self, wf) -> list
  · ActionsAllowUnsecureCommands — `ACTIONS_ALLOW_UNSECURE_COMMANDS=true` re-enables `::set-env::`.
  · ActionsAllowUnsecureCommands.check(self, wf) -> list
  · IdTokenWriteUnscoped — `id-token: write` permission without an `environment:` gate.
  · IdTokenWriteUnscoped.check(self, wf) -> list
`scripts/lib/sentinel/rules_injection.py` — Structural injection-detection rules (Python port of the Sentinel reference).
  · ShellInjectionExpr — Attacker-controllable ${{ }} expression interpolated into a run: block.
  · ShellInjectionExpr.check(self, wf) -> list
  · GithubScriptInjection — Attacker-controllable ${{ }} expression inside an actions/github-script step.
  · GithubScriptInjection.check(self, wf) -> list
  · ShellInjectionJq — Attacker-controlled shell variable interpolated in a double-quoted jq/curl string.
  · ShellInjectionJq.check(self, wf) -> list
  · WorkflowDispatchInjection — User-controlled workflow_dispatch input interpolated into a run: block.
  · WorkflowDispatchInjection.check(self, wf) -> list
  · DangerousTriggers — pull_request_target combined with an explicit checkout of fork/PR head code.
  · DangerousTriggers.check(self, wf) -> list
  · RunsOnInjection — Attacker-controllable expression interpolated into `runs-on:`.
  · RunsOnInjection.check(self, wf) -> list
  · IssueCommentToctou — `issue_comment` trigger + checkout of head ref → TOCTOU window.
  · IssueCommentToctou.check(self, wf) -> list
`scripts/lib/sentinel/rules_repo.py` — Repo-level Sentinel rules — checks that span the whole repository rather
  · missing_zizmor(workflow_texts) -> list[Finding] — Repo-level: no workflow runs the zizmor static analyzer anywhere.
`scripts/lib/state.py` — Shared state helpers for ai-maestro-janitor hooks and detectors —
  · set_project_dir_override(cwd) -> None — Record a fallback project dir used only when CLAUDE_PROJECT_DIR is unset.
  · project_root(cwd_override) -> Path
  · janitor_root() -> Path
  · state_dir() -> Path
  · log_dir() -> Path
  · init_state() -> None — Create state/ and logs/ directories if missing. Idempotent.
  · atomic_write(target, value) -> None — Atomic-by-rename write: write to tmp, then os.replace into place.
  · user_presence_path(home) -> Path — Path of the cross-plugin user-presence breadcrumb under HOME.
  · bump_user_presence(home, now) -> None — Record a GENUINE user-input event — stamp BOTH epochs to `now`.
  · refresh_user_presence_written_at(home, now) -> None — Refresh the breadcrumb's liveness (written_at_epoch) WITHOUT touching input recency.
  · read_int_state(path, default) -> int — Read a non-negative int from a state file.
  · is_truthy_env(name, default) -> bool — Read a yes/no env var with friendly false-spellings.
  · coerce_int(value, default, *, detector_name, var_name) -> int — Coerce a (possibly user-supplied) value to a non-negative int.
  · autofix_mode() -> str — Return the current autofix mode for this project — "on" or "off".
  · autofix_enabled() -> bool — True iff the "act, don't ask" autofix policy is active.
  · autofix_disabled() -> bool — True iff `/janitor-autofix-off` has been run in this project.
  · is_self_scan_target() -> bool — True iff the current `CLAUDE_PROJECT_DIR` is the janitor's own repo.
  · file_mtime(path) -> int — Return file mtime in epoch seconds, or 0 on error.
  · log_line(name, message) -> None — Append one log line with a local-time timestamp + GMT offset.
  · rotate_log_if_big(name, max_bytes) -> None — Rotate <name>.log to <name>.log.1 when it exceeds `max_bytes`.
  · run_subprocess(cmd, *, timeout, cwd, capture, detector_name) -> Optional[subprocess.CompletedProcess[str]] — Run a subprocess with a default timeout, never propagate exceptions.
  · sanitize_for_drift_line(text) -> str — Defang `[` `]` and strip control characters from untrusted text.
`scripts/lib/suppression.py` — Shared suppression-file loader for janitor detectors.
  · SuppressionRule — A single, parsed suppression entry.
  · SuppressionRule.is_expired(self, today) -> bool
  · SuppressionRule.matches(self, rule_id, file, sha) -> bool
  · SuppressionTable — The full set of suppression entries for a project root.
  · SuppressionTable.is_suppressed(self, rule_id, file, sha) -> bool
  · load(project_root) -> SuppressionTable — Load the project's suppression table.
`scripts/lib/user_mem_lib.py` — USER-MEMORY subsystem core (TRDD-4334aad0) — a PRIVATE, agent-invisible
  · resolve_user_mem_dir(project_dir) -> Path — Return the user-mem store dir for a project (does not create it).
  · SearchResult — One memgrep hit, annotated with the memory's immutable number.
  · UserMemStore — The on-disk user-memory store: one markdown file per memory + a monotonic,
  · UserMemStore.path_for(self, number) -> Path — The canonical file path for a memory number (zero-padded, sortable).
  · UserMemStore.save(self, text) -> int — Persist `text` as a new memory; return its immutable number.
  · UserMemStore.read(self, number) -> Optional[str] — Return memory #number's body text, or None if it was never assigned /
  · UserMemStore.delete(self, number) -> bool — Remove memory #number's file. Returns True if a file was removed.
  · UserMemStore.search(self, query, *, memgrep, top) -> list[SearchResult] — Run `memgrep find <query> <this-dir> --use-index` and return numbered hits.
  · build_search_argv(query, store_dir, *, memgrep, top) -> list[str] — Build the `memgrep find <query> <store_dir> --use-index --top <top>` argv.
  · previous_user_message(transcript_path) -> Optional[str] — Return the text of the user message immediately BEFORE the /to-user-mem line.
  · parse_command(prompt) -> tuple[Optional[str], str] — Classify a submitted prompt as one of our commands.
  · find_memgrep() -> Optional[str] — Resolve the memgrep binary path (env override → PATH → cargo bin).
`scripts/lib/version_update_lib.py` — Shared janitor self-update helpers — used by the daemon's
  · detect_install_scopes() -> list[str] — Return every scope where the plugin is referenced.
  · list_installed_versions(parent) -> list[str] — Semver-shaped subdir names of `parent`, sorted ascending.
  · resolve_latest_published(plugin_root) -> str | None — GitHub releases/latest tag for the repo declared in plugin.json.
  · attempt_auto_update(log_writer, update_log_path) -> bool — Refresh marketplace + run `claude plugin update` per scope.
  · do_auto_update_if_needed(plugin_root, log_writer, update_log_path) -> tuple[bool, str] — Run the cache-vs-GitHub check + auto-update in one go.
`scripts/lib/zizmor_classifier.py` — One-pass workflow classifier — google-re2 RegexSet primary, Python re fallback.
  · Finding
  · Classifier — Single-pass workflow classifier. Build once, reuse across files.
  · Classifier.classify(self, text) -> Iterator[Finding]
  · Classifier.re2_active(self) -> bool
`scripts/lib/zizmor_patterns_extra.py` — Extension catalog for the janitor's second-pass workflow auditor.
`scripts/oauth_rotator/cascade.py` — The OAuth-rotator cascade — ONE paradigm in three parts, each falling back to
  · CascadeLeg — Which leg of the ROTATE→RENEW→REAUTH cascade an ALTERNATE account sits in.
  · AccountState — The cascade-relevant facts about ONE account — all non-secret metadata.
  · classify(acct, *, keepalive_ahead_h, login_grace_days) -> CascadeLeg — Classify ONE account into its cascade leg. The SSOT both daemon + detectors use.
  · CascadePlan — The fleet-level RENEW/REAUTH buckets, in cascade order. ROTATE is reported
  · CascadePlan.summary_line(self) -> str — A compact, log-friendly one-liner naming the non-empty fallback legs.
  · cascade_plan(accounts, *, keepalive_ahead_h, login_grace_days) -> CascadePlan — Classify every account and bucket the ALTERNATES into the cascade's fallback
`scripts/oauth_rotator/cookie_vault.py` — Cookie-jar mechanics for the rotator (TRDD-dfc0959a Phase 2): EXTRACT a Chrome
  · CookieJar — A portable snapshot of one account's claude.ai cookies.
  · CookieJar.names(self) -> tuple[str, ...] — The cookie names in the jar (for logging / assertions — never the values).
  · extract_jar(cookies_db, *, host_filter) -> CookieJar — Read every cookie whose ``host_key`` matches ``host_filter`` from a Chrome Cookies
  · jar_to_json(jar) -> str — Serialise a CookieJar to a compact JSON string (the form stored in safe_storage).
  · jar_from_json(payload) -> CookieJar — Parse a jar previously produced by ``jar_to_json``. Raises ValueError on a version
  · inject_jar(cookies_db, jar) -> int — Write every row of ``jar`` into the Cookies sqlite at ``cookies_db`` (created with
  · snapshot_to_keychain(email, cookies_db, *, host_filter) -> safe_storage.StoreResult — Extract ``email``'s claude.ai cookies from its Chrome profile and store the jar
  · materialize_from_keychain(email, cookies_db) -> int | None — Load ``email``'s stored cookie jar from safe-storage and INJECT it into the Chrome
  · forget_in_keychain(email) -> None — Best-effort removal of ``email``'s stored cookie jar from safe-storage (retiring
`scripts/oauth_rotator/reauth.py` — Tier-3 OAuth re-auth — refresh the LIVE Claude credential, hands-free.
  · log(msg) -> None
  · die(msg, code) -> NoReturn
  · tmux(*args, timeout) -> subprocess.CompletedProcess[str]
  · tmux_running(session) -> bool
  · capture_pane(session) -> str
  · kill_session(session) -> None
  · wait_for(session, predicate, *, timeout, interval, label) -> str | None — Poll capture-pane until predicate(text) is truthy, the session exits, or
  · resolve_intended_email(arg_email) -> str | None
  · authorize_and_capture_code(cdp_url, authorize_url, intended_email, *, nav_timeout_ms, click_timeout_ms, redirect_timeout_ms) -> tuple[bool, str, str | None] — Connect to the logged-in browser over CDP, open the consent URL, run the
  · main(argv) -> int
`scripts/oauth_rotator/rotator.py` — Claude Code multi-subscription account rotator.
  · SlotKeychainWriteError — A keychain/keyring was PRESENT but refused a slot write — fail CLOSED.
  · migrate_root_to_canonical() -> tuple[Path, Path, bool] — One-time: copy ``state.json`` + ``opt-in.flag`` from the legacy standalone root
  · read_live_blob() -> dict | None — The live credential, robust against a corrupt/missing primary: the PRIMARY store ladder
  · write_live_blob(blob) -> None — Overwrite the live credential with `blob`, cross-platform.
  · fingerprint(blob) -> str
  · expires_in_h(blob) -> float | None
  · load_state() -> dict — Read the state index with corruption recovery (TRDD-7100178d, Pillar 2). The
  · save_state(state) -> None — Persist the state index with an in-advance backup: `integrity.backup_and_write`
  · slot_path(email) -> Path — Legacy plaintext slot path — kept ONLY for the no-keychain fallback (Linux
  · write_slot(email, blob) -> None — Persist an account's slot token ENCRYPTED in the OS keychain — to BOTH the primary
  · read_slot(email) -> dict | None — Read an account's slot token: primary keychain → backup keychain (Pillar 2 mirror,
  · migrate_slots_to_keychain() -> list[tuple[str, bool]] — One-time: copy every legacy plaintext `slots/<email>.json` into the keychain
  · delete_plaintext_slot_files() -> list[str] — Remove the legacy plaintext `slots/*.json` files (security cleanup, only AFTER
  · claude_running() -> bool — True iff a real Claude Code CLI process is running.
  · account_email(blob) -> str | None — Resolve the account email via the roles endpoint. Network call.
  · usage_request(blob) -> tuple[int, dict | None] — Probe /api/oauth/usage. Returns (http_status, data).
  · account_usage(blob) -> dict | None — Convenience wrapper for display: the usage dict on HTTP 200, else None.
  · refresh_oauth_token(blob) -> dict | None — Exchange a SLOT's refreshToken for a fresh token pair at the OAuth token endpoint and
  · cmd_capture(only_if_running) -> int
  · cmd_list() -> int
  · cmd_switch(email) -> int
  · cmd_usage() -> int — Print live + every slot's 5h/7d utilization. Zero inference cost.
  · is_near_limit(fh, sd) -> bool — The LIVE account is 'near a limit' (→ rotate away) once EITHER window
  · is_safe_alternate(bfh, bsd) -> bool — An alternate is a safe rotation TARGET only if it is below SAFE on BOTH
  · select_drain_first(candidates) -> tuple[str, dict, float, float] | None — DRAIN-FIRST selection (user decision 2026-05-29, TRDD-32acd15f). Among
  · cmd_auto() -> int — Proactive usage-based rotation. No-op unless the LIVE account is near a
  · cmd_tick(only_if_running) -> int — One daemon beat: migrate the legacy root once, keepalive-refresh slot tokens nearing
  · cmd_live_email() -> int — Print the authoritative email of the CURRENTLY LIVE account, or empty.
  · cmd_known_emails() -> int — Print every known account email (live + all slots), one per line.
  · cmd_print_profiles_root() -> int — Print the canonical Chrome-profiles root (``_profiles_root()``).
  · cmd_oauth_health(as_json) -> int — Print per-account OAuth health (has_refresh + expiry) read from the KEYCHAIN.
  · main(argv) -> int
`scripts/oauth_rotator/safe_storage.py` — Cross-platform OS secret storage — the single abstraction for keeping rotator
  · StoreResult — Outcome of a ``store`` call — three-valued so callers can fail closed.
  · detect_backend() -> str — Return the active backend id: ``macos`` | ``secret_tool`` | ``dpapi`` | ``none``.
  · store(service, account, secret) -> StoreResult — Store ``secret`` (an opaque string — the caller serialises) ENCRYPTED under
  · retrieve(service, account) -> str | None — Return the stored secret string for (``service``, ``account``), or ``None`` if
  · delete(service, account) -> None — Best-effort removal of (``service``, ``account``) from the active backend.
  · macos_store_argv(service, account, secret) -> list[str] — `security add-generic-password` argv with the value ON ARGV (`-w <secret>`).
  · macos_retrieve_argv(service, account) -> list[str]
  · macos_delete_argv(service, account) -> list[str]
  · secret_tool_store_argv(service, account) -> list[str]
  · secret_tool_retrieve_argv(service, account) -> list[str]
  · secret_tool_delete_argv(service, account) -> list[str]
`scripts/oauth_rotator/slot_capture_browser.py` — Automated full-OAuth slot capture via the account's OWN Chrome profile.
  · profile_dir(email) -> Path
  · capture(email, headless) -> int
  · main(argv) -> int
`scripts/oauth_rotator/slot_capture_token.py` — Capture a `claude setup-token` long-lived token into a rotator slot.
  · read_token() -> str — Read the token from (in order): a hidden TTY prompt, piped stdin, or — as
  · main() -> int
`scripts/oauth_rotator/supervisor.py` — OAuth-rotator supervisor — the governance layer (TRDD-32acd15f, P2).
  · opt_in_present(root) -> bool — True iff `/janitor-auto-manage-oauth-on` wrote the opt-in flag.
  · SlotFact — Observable, non-secret metadata for one captured account slot.
  · Facts — Everything `diagnose` needs, gathered by `gather_facts` (the only I/O).
  · Finding — One supervisor conclusion — always an alert a human must act on (the
  · diagnose(facts) -> list[Finding] — PURE: turn gathered facts into alert findings. No I/O.
  · gather_facts(root, *, now) -> Facts — Collect every observable fact `diagnose` needs. The ONLY I/O entry point.
  · SupervisorResult — What `apply` did — alert codes recorded + logged (no heals: the daemon
  · apply(findings, *, log) -> SupervisorResult — Record + log every alert finding. The supervisor heals nothing now that
`scripts/publish.py` — Strict publish pipeline: auto-detect → test → lint → validate → consistency → bump → commit → push.
  · ensure_pre_push_hook(git_root) -> None — Install / refresh the pre-push hook and activate core.hooksPath.
  · detect_git_root() -> Path — Find the git repository root (handles subfolder plugins).
  · detect_plugin_root() -> Path — Find the plugin root by walking up from this script to find .claude-plugin/plugin.json.
  · detect_plugin_info(plugin_root) -> dict — Read plugin metadata from .claude-plugin/plugin.json.
  · detect_marketplace(git_root) -> dict — Auto-detect marketplace info from git remote and plugin structure.
  · detect_default_branch(git_root) -> str — Detect the default branch (main or master).
  · ProjectKind
  · ProjectInfo — Auto-detected project metadata. `kind` is the primary language/ecosystem;
  · ProjectInfo.all_kinds(self) -> list[ProjectKind] — Primary + secondary kinds, deduplicated.
  · ProjectInfo.has_kind(self, kind) -> bool
  · detect_project(root) -> ProjectInfo — Auto-detect project type and metadata from root config files.
  · language_test_step(info) -> None — Run every applicable language's test suite. Mandatory — any failure
  · language_lint_step(info) -> None — Run every linter that has matching files in the tree.
  · language_bump_version(info, new_version) -> list[tuple[bool, str]] — Bump version in every applicable config file for the detected kinds.
  · ensure_git_cliff_available() -> None — Fail fast if git-cliff is not on PATH.
  · ensure_cliff_config(root) -> None — Create a default cliff.toml if the repo doesn't have one.
  · run_git_cliff(root, new_version) -> str — Run git-cliff to (re)generate CHANGELOG.md and extract release notes.
  · ensure_cliff_gitignore(root) -> None — Add the release-notes scratch file to .gitignore if not already there.
  · run(cmd, cwd, *, check) -> subprocess.CompletedProcess[str] — Run a command, print it, stream output, and fail fast on error.
  · parse_semver(version) -> tuple[int, int, int] | None — Parse 'X.Y.Z' into (major, minor, patch), or None if invalid.
  · bump_semver(current, bump_type) -> str | None — Bump version by type ('major', 'minor', 'patch'). Returns new version or None.
  · get_current_version(plugin_root) -> str | None — Read current version from .claude-plugin/plugin.json.
  · update_plugin_json(plugin_root, new_version) -> tuple[bool, str] — Update version field in plugin.json.
  · update_pyproject_toml(plugin_root, new_version) -> tuple[bool, str] — Update version field in pyproject.toml.
  · update_python_versions(plugin_root, new_version) -> list[tuple[bool, str]] — Update __version__ = 'X.Y.Z' in all Python files.
  · check_version_consistency(plugin_root) -> tuple[bool, str] — Check all version sources match. Returns (ok, message).
  · do_bump(plugin_root, new_version, dry_run) -> bool — Bump version across all files. Returns True on success.
  · main() -> int
`scripts/safe_delete.py` — safe-delete — Python port of safe-delete.sh.
  · main() -> int
### Convention groups
`scripts/lib/*_patterns.py` (×223) [ad_ldap, agent_config, ai_agent_runtime, ai_jailbreak, api_gateway, apns_fcm_push, apple_privacy_manifest, archive_extraction, argocd_fluxcd, artifact_storage_creds, … +213 more]
<+-+-JANITOR-REPO-MAP-END-(do-not-modify)-+-+>
