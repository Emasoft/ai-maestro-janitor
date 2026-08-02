---
name: janitor-core-files-reference
description: "what does dispatch.py do / what does daemon.py do / what is in scripts/lib/state.py / global_state.py responsibilities / where is publish.py / what does usage_probe.py throttle / which script is the janitor self-update / a file-by-file reference of scripts/ and scripts/lib/ core modules"
ocd: 2026-08-02
lmd: 2026-08-02
metadata:
  node_type: memory
  type: reference
  tier: component
  functionality: core-files-reference
---

# janitor-core-files-reference


^ATOM-SVVF-IY1P [desc:"Verified core-files reference: top-level scripts/ (dispatcher-stub, dispatch, daemon, doctor, publish, safe_delete, branch_protection_apply) and scripts/lib/ core modules (state, global_state, dedupe,", keywords: top_level_scripts_core_files_list dispatcher-stub_dispatch_daemon_publish_safe_delete_branch_protection_apply scripts_lib_core_state_global_state_dedupe_version_update_lib_rules_installer_usage_probe, type: reference, ocd: 2026-08-02, lmd: 2026-08-02]

### Core files (verified)

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
- `global_state.py` — daemon contract: `global_state_dir` (⚠️ unofficial path), the DUAL-ERA singleton (`acquire/release_singleton_dual` — holds every era's `daemon.flock`, control_dir() first; the old single-fd `acquire_singleton_flock` is retired, TRDD-QK7M2B0X), **`marketplace_lock`/`acquire/release_marketplace_lock`** (cross-process serialization), daemon lifecycle (`daemon_pid` live-preferring dual-read, `write/read_heartbeat` dual-write/max-read, `foreign_era_daemons` double-daemon detector, `kill_switch_present`, `daemon_is_alive`, `ensure_daemon_running`, `spawn_daemon_detached`, `daemon_needs_restart`, `set/clear_reload_flag`).
- `dedupe.py` — `emit_once` (content-hash dedupe → unchanged findings stay silent).
- `version_update_lib.py` — janitor self-update helpers (`attempt_auto_update`, `do_auto_update_if_needed`, `detect_install_scopes`); daemon-only caller.
- `rules_installer.py` — `install_rules` copies plugin `rules/*.md` into the active scope's `.claude/rules/` (atomic tmp+replace; content-exact idempotency). Called by `on-session-start`. **Rules lifecycle (TRDD-H9IBY95W):** each shipped rule carries a leading inert-guard + `PROVENANCE_MARKER` comment (`ai-maestro-janitor:installed-rule`) → the rule self-disables when the janitor is DISARMED (kill-switch flag) and flags itself INERT + never-delete-memory when UNINSTALLED (data dir absent). `remove_orphaned_rules` (per-session, called by on-session-start after install) strips marker-bearing rules from any scope that's no longer an install target (partial uninstall / redundant project mirror); `cleanup_user_orphans_if_uninstalled` (daemon `rules-cleanup` task) removes user-scope orphans once `janitor_uninstalled()` (no settings scope AND no data dir). ALL removal is marker-gated `*.md`-only → never a user's own rule, never a memory store. Ships 8 rules; the set is AUTO-DISCOVERED by globbing `rules/*.md` (no hardcoded list). Includes the 3 IND governance rules `trdd-design-tasks`/`prrd-design-rules`/`universal-kanban` (issue #73, the ai-maestro-independent half of the 3-pillars split). INSTALL compares BYTES not markers, so it OVERWRITES an existing unmarked same-named user rule → the content-based overwrite is the one-shot takeover of the user's old hand-placed globals (marker-gating protects only the REMOVAL path, never the install).
- `usage_probe.py` — the ONE throttled reader of `/api/oauth/usage` (TRDD-WEBA1RMF). Single writer, N readers: `rotator.usage_request` → this, so the rotator's 60 s beat and `window-burn-rate`'s 15 min share one budget. Sends `claude-code/<version>` (derived from `claude --version`) because that endpoint drops any other UA into an aggressive bucket that 429s persistently — and a probe 429 is read by the rotator as "account MAXED", so a throttle makes live AND every alternate look unusable at once and rotation stalls (the 2026-07-18 deadlock, TRDD-WBYFTU2L). **Two hosts, two OPPOSITE correct UAs:** `platform.claude.com/v1/oauth/token` still needs `claude-account-rotator` (urllib's default → Cloudflare 1010); pinned by `tests/test_oauth_token_useragent.py`. Per-account cache keyed by a salted token digest (mtime IS the TTL clock, 600 s), `Retry-After`/`anthropic-ratelimit-*-reset` honoured else exponential 600→7200 s, non-blocking flock with a post-acquire re-check (TOCTOU) and a `_NO_LOCK` sentinel for lock-less homes, `outcome["reason"]` so staleness names its true cause. **Resolves NO credential** — it is handed a token; `rotator._read_live_primary()` keeps the cross-platform ladder (macOS Keychain → `.credentials.json` → `secret-tool`), so a telemetry probe can never raise a keychain dialog. Throttling design adapted from ccgauge (MIT).
- others: `branch_protection_lib`, `git_utils`, `git_ops_patterns`, `posture`/`posture_modes`, `suppression`, `output_formats`, `security_helpers`, `ioc_taxonomy`, `janitor_self_integrity`, `zizmor_classifier`/`zizmor_patterns*`, `sentinel/` (workflow-doctor rule engine: `model`, `rules_absence/context/injection/extra/repo`).

## Governed by

- [[janitor-architecture]] — the architecture hub.

## Notes and lessons learned
