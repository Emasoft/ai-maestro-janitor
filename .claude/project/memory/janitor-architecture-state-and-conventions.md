---
name: janitor-architecture-state-and-conventions
description: "where should persistent state be written / what is CLAUDE_PLUGIN_ROOT vs CLAUDE_PLUGIN_DATA / where does janitor state live / what is the ONE SANCTIONED EXCEPTION folder ~/.claude/janitor-control / which project rules PRRD pointers shape the architecture / is the legacy janitor-global-state dir safe to delete / which code still touches the legacy janitor-global-state dir / does the daemon still read the legacy global-state folder / arm did not stick on an un-migrated host / a cleared STOP was resurrected by the migration / what is the runtime installed tree layout / show me the on-disk layout of the janitor"
ocd: 2026-06-13
lmd: 2026-09-02
metadata:
  node_type: memory
  type: project
  tier: component
  globs:
    - "CLAUDE.md"
    - "design/requirements/PRRD.md"
publish-globally: false
split-lineage: 959060b8fb99469c8afe79d502cf3dac
---

# ai-maestro-janitor — filesystem, state conventions & project rules

## Filesystem & state conventions

| Path | Resolves to | Lifecycle | Use for |
|---|---|---|---|
| `${CLAUDE_PLUGIN_ROOT}` | the versioned plugin cache dir | **ephemeral** — changes every update, GC'd ~7 days | scripts, skills, hooks. **NEVER write state here.** |
| `${CLAUDE_PLUGIN_DATA}` | the per-plugin persistent data dir | **persistent** — survives updates, backed up, purged only on uninstall | ALL persistent state, caches, venvs. **Prefer this** (PRRD S4.1). |
| `<repo-root>/.janitor/state/` | per-project | per-project | per-session detector state (last-run stamps, seen-files, resume/rate-limit flags) |

The **auto-rolling dispatcher stub** lives in `${CLAUDE_PLUGIN_DATA}` (correct —
survives version bumps). The daemon's **private** global state is CANONICALLY at
`${CLAUDE_PLUGIN_DATA}/global-state/` since TRDD-2U8AH82F.[^4] Its
**coordination** state — anything a SECOND chore owner must observe or contend
on — instead lives at the fixed `~/.claude/janitor-control/`: see
[[janitor-fleet-control-plane]] for the split, which is audience-based, not a
reversal of the DATA-dir principle.[^11]
Existing installs are migrated automatically by the daemon under its singleton
flock (flock-moves-LAST: the NEW dir's flock is acquired before the
`migrated-from-legacy.ts` marker flips resolution). **RETIRED (TRDD-ULEGRT01):**
the legacy `$HOME/.claude/janitor-global-state/` dir is no longer a dual-read
fallback — `global_state_dir()` is now a 3-rung ladder (env override → XDG →
the DATA dir unconditionally) and control-flag readers span only
`control_dir()` + `global_state_dir()`. The legacy dir survives only as
`_legacy_global_state_dir()`, whose sole caller is the never-migrated-host
migration path (see ^ATOM-EXPB-DEFP).

**Principle (per the project owner):** prefer `${CLAUDE_PLUGIN_DATA}` over any
new `$HOME/.claude/<custom>/` folder — the data dir is the only location
guaranteed preserved across plugin/marketplace/version changes, picked up by
backups, and cleanly purged on uninstall.

## Project rules (PRRD pointers)

The constitution is `design/requirements/PRRD.md`. The rules that most shape the
architecture: **G1.1** (GitHub posts self-identify the authoring Claude — all
AI Maestro agents share the one owner gh identity); **S2.1** (the scope
invariant above); **S3.1** (atomic user-scope file writes); **S4.1** (state in
`${CLAUDE_PLUGIN_DATA}`); **S5.1** (publish validates via the CPV plugin only —
clear a finding by devitalizing/removing code, never by suppressing a rule or
relaxing `--strict`); **S6.1** (every detector is fail-soft).

## Historical detail (atoms, verbatim)

^ATOM-MQ9L-E7LV [desc:"Filesystem & state conventions table + current state locations + the ONE SANCTIONED EXCEPTION principle box for ~/.claude/janitor-control/ (verbatim)", keywords: filesystem_state_conventions_table CLAUDE_PLUGIN_ROOT_ephemeral_CLAUDE_PLUGIN_DATA_persistent one_sanctioned_exception_janitor-control_folder global_state_dir_ladder_migration where_should_persistent_state_be_written why_is_janitor-control_not_migrated_into_the_data_dir what_does_global_state_dir_resolve_to why_must_the_control_plane_be_a_fixed_literal_path_for_the_ai-maestro_server what_lives_in_the_legacy_global_state_folder what_is_CLAUDE_PLUGIN_DATA, type: project, ocd: 2026-08-02, lmd: 2026-08-02] [^13]

### Filesystem & state conventions (per plugins-reference.md)

| Path | Resolves to | Lifecycle | Use for |
|---|---|---|---|
| `${CLAUDE_PLUGIN_ROOT}` | `~/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/<version>/` | **Ephemeral** — changes every update, GC'd ~7d | scripts, skills, hooks. **NEVER write state here.** |
| `${CLAUDE_PLUGIN_DATA}` | `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/` | **Persistent** — survives updates, backed up, purged only on uninstall | ALL persistent state, caches, venvs. **Prefer this.** |
| `$CLAUDE_PROJECT_DIR/.janitor/state/` | per-project | per-project | per-session detector state |

**Current state locations:**
- ✅ `dispatcher-stub.py` → `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py` (correct).
- ✅ per-session → `$PROJECT/.janitor/state/` (correct — project-scoped).
- ✅ **daemon global state → `${CLAUDE_PLUGIN_DATA}/global-state/`** (TRDD-2U8AH82F, era-1 legacy retired by TRDD-ULEGRT01). `global_state.py::global_state_dir` ladder is now 3 rungs: env override → XDG → the DATA dir UNCONDITIONALLY — **no legacy rung**. Control-flag readers span only `control_dir()` + `global_state_dir()`, never the legacy path. Legacy `~/.claude/janitor-global-state/` is fully **RETIRED**; only `_legacy_global_state_dir()` survives, and its sole caller (`migrate_global_state_to_data_dir()`) still runs on a never-migrated host, gated by the explicit predicate `(migrated-from-legacy.ts absent) AND (legacy dir exists)` (see ^ATOM-88DL-HFDJ).

> **Principle (per user):** prefer `${CLAUDE_PLUGIN_DATA}` over any new
> `~/.claude/<custom>/` folder. The data dir is the only one guaranteed
> preserved across plugin/marketplace/version changes, backed up by backup
> tools, and cleanly purged on uninstall. Unofficial folders are lost by
> backups AND left as orphan junk by purge.
>
> **THE ONE SANCTIONED EXCEPTION — `~/.claude/janitor-control/`** (owner, 2026-07-21:
> *"this folder is an exception, introduced necessarily because of the shared flags with
> the ai-maestro server"*). It holds the fleet control plane (ARCHITECTURE.md §7.1;
> TRDD-QK7M2B0X) — the global MODE flags, the coordination LOCKS, the per-chore last-run
> stamps, and the daemon singleton: everything a SECOND chore owner must observe or
> contend on. That scope rule is audience, not kind — splitting coordination data across
> two directories is how two daemons desynchronise, and a `flock` the other daemon cannot
> see excludes nobody. It is a fixed path because an ai-maestro server must stat one
> LITERAL path — `global_state_dir()`'s four-rung ladder is unreproducible by a foreign
> reader, and guessing a rung fails silently as "flag absent", i.e. it ignores the control
> plane while looking healthy. **Do NOT migrate this folder into the DATA dir**; the
> principle's virtues (survives updates, backed up) are the exact properties a mode flag
> must NOT have — an uninstalled janitor must leave nothing behind claiming the host is in
> maintenance. Everything else — pid, flock, heartbeat, last-run stamps, injection stamps —
> stays in `<DATA>/global-state/` and the principle governs it unchanged.

^ATOM-UZAL-KYBJ [desc:"The Runtime / installed tree ASCII diagram (verbatim) showing every on-disk path the plugin uses", keywords: runtime_installed_tree_diagram plugin_cache_data_dir_memory_mirror_legacy_global_state_layout per_project_janitor_state_files_list what_does_the_janitor_installed_tree_look_like where_is_the_plugin_cache_directory where_is_the_per_project_janitor_state_folder show_me_the_on-disk_layout_of_the_janitor what_is_the_memory_mirror_directory where_do_per-project_janitor_state_files_go what_is_the_legacy_global_state_layout, type: project, ocd: 2026-08-02, lmd: 2026-08-02] [^14]

### Runtime / installed tree

```
~/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/<ver>/  ephemeral plugin (scripts/skills/hooks)
~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/         DATA: dispatcher-stub.py + CANONICAL USER memory/ + global-state/ (canonical daemon state since TRDD-2U8AH82F)
~/.claude/ai-maestro-janitor-memory/                                  USER-memory backup MIRROR (TRDD-GFT33HT9): SessionStart syncs primary→mirror + restores mirror→primary; survives a plain uninstall (data dir deleted). memory_scopes.{resolve_user_mirror_dir,sync_user_memory_mirror}
~/.claude/janitor-global-state/                                       RETIRED (TRDD-ULEGRT01) — no resolver rung, no flag READ. Three deliberate
                                                                       exceptions: the one-time migration reads it, `_flag_clear_dual` still
                                                                       UNLINKS there (a clear must reach every path a flag can be read from, or
                                                                       the migration copies a cleared STOP forward), and
                                                                       `safe_storage::_legacy_keychain_latch_path` reads the keychain latch.
                                                                       On pre-migration hosts it once held: daemon.pid · daemon.flock ·
                                                                       daemon.heartbeat.ts · daemon.spawn-attempt.ts · marketplace-op.lock ·
                                                                       {marketplace-refresh,version-update}.last-run.ts · kill-switch.flag ·
                                                                       reload-needed.flag · skills-reload-needed.flag ·
                                                                       version-update-requested.flag. Safe to remove once
                                                                       DATA/global-state/migrated-from-legacy.ts exists (see ^ATOM-V89R-2RUZ).
$PROJECT/.janitor/state/                                              per-session: last-run-<detector>.ts ·
    rate-limited.flag · rate-limited-since.ts · resume-after-compact.flag · resume-after-compact.ts ·
    resume-directive.txt (agent pointer) · heartbeat-armed-at.ts · heartbeat-renew-seen.txt · <detector> seen-files ·
    desired-cadence.cron · armed-cadence.cron · cadence-state.json · ttl-regime.json · last-resume.ts (TTL-aware cadence, TRDD-0QQX9H0G)
cron: one CronCreate per project (SESSION-SCOPED by design; no `durable` param exists) → fires the stub
```


^ATOM-0EBD-0XQE [desc: "the launchd-run daemon carries NONE of settings.json's env block — every CLAUDE_PLUGIN_OPTION_* it read from os.environ sat at its default until 3.4.4; daemon-lane code reads options via state.plugin_", keywords: daemon_ignores_CLAUDE_PLUGIN_OPTION lever_true_in_settings.json_but_daemon_still_shadow launchd_daemon_has_no_settings_env plugin_option_not_applied_to_daemon setting_changed_but_daemon_behaviour_unchanged external_clear_still_dry-run_after_enabling ps_-E_daemon_environment_empty state.plugin_option plugin_options_env_child_env where_does_the_daemon_read_its_options, type: project, trdd: TRDD-XCJFCJUX, ocd: 2026-09-02, lmd: 2026-09-02]

Measured 2026-09-02 (TRDD-XCJFCJUX): the OS-keepalive daemon (launchd) had ZERO `CLAUDE_PLUGIN_OPTION_*` variables in its environment (`ps -E` snapshot; the plist has no `EnvironmentVariables`; `launchctl getenv` empty) while `~/.claude/settings.json` had `CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED: "true"` — so the external clear ran in `[SHADOW — dry-run]` on every beat and every other daemon knob (intervals, DAEMON_ENABLED, COLD_CACHE_CLEAR_SHADOW, …) silently sat at its default since the keepalive became the production path. Claude Code injects the settings env block into SESSIONS only; a heartbeat-spawned daemon inherits it, a launchd-spawned one does not. Since 3.4.4: daemon.py loads the file's options into a dict mirror at import (gated on `_KEEPALIVE_INSTANCE`, before the interval constants are computed) and refreshes on mtime each tick; ALL daemon-lane option reads go through `state.plugin_option(name)` (real env wins) and every child spawn merges `state.plugin_options_env()`. Rule for new code on the daemon path: never `os.environ.get("CLAUDE_PLUGIN_OPTION_…")` directly — use the accessor, or a launchd host ignores the knob. Diagnose the class with: `ps -E -p <daemon pid> -o command= > snap.txt; grep -c CLAUDE_PLUGIN_OPTION_ snap.txt`.


^ATOM-2IUL-97C3 [desc: "launchd daemon's llm-ext child has no OPENROUTER_API_KEY (harness-injected into sessions, no file defines it): every automated clear logs NO_SUMMARY_POST_CLEAR and resumes from the stale mechanical ha", keywords: NO_SUMMARY_POST_CLEAR requires_api_key_env_var_not_set OPENROUTER_API_KEY_not_set automated_clear_resumed_from_precompact-handoff llm-ext_failed_under_the_daemon daemon_launchd_no_env summary_hold_expired_mechanical_handoff identical_failure_x3_giving_up clear_fired_but_no_summary openrouter-remote_requires_api_key daemon_cannot_see_api_key first_automated_clear_no_summary where_does_the_session_get_OPENROUTER_API_KEY, type: project, trdd: TRDD-QZVAEWQH, ocd: 2026-09-02, lmd: 2026-09-02]

The launchd daemon's children inherit NO harness-injected secrets, just as they inherit no settings.json options (ATOM-0EBD-0XQE): `lib/external_clear.run_llm_ext_summary` spawns `llm-ext` with the daemon's own `os.environ`, and under launchd that carries no `OPENROUTER_API_KEY`. Interactive sessions DO have it — but from the desktop harness that launches Claude Code, not from any file: `~/.zshenv`/`.zprofile`/`.zshrc`/`.zautovenv`, the `.env` candidates, `launchctl getenv`, settings.json's `env` block and the keychain (by that account name) all define nothing, so no rc-sourcing trick can hand it to the daemon. The first live automated clear (AgentlensPro, 2026-09-02 04:23:48, `next-fire-misses`, 418k context) therefore ran its cheap half perfectly (fired 04:23:51, re-armed 04:24:45, resume cue 04:25:03) and its whole point dark: three identical `Remote api 'openrouter-remote' requires 'api_key' (env var $OPENROUTER_API_KEY is not set)` failures, `NO_SUMMARY_POST_CLEAR`, a 15-minute summary hold, and a resume from the stale mechanical `precompact-handoff.md` (a day old). The XCJFCJUX mirror `state.plugin_options_env` covers `CLAUDE_PLUGIN_OPTION_*` ONLY, by design — do not widen it silently; credential placement is a USER ruling (TRDD-QZVAEWQH: settings.json env allowlist / SessionStart capture / llm-ext keychain). Diagnose from `global-state/external-clear.log` — `cold-cache-clear.log` shows only the verdict and the degrade line, never the llm-ext stderr.

## Governed by

- [[janitor-architecture]] — the architecture overview hub this page details.

## Notes and lessons learned

[^4]: [id:ATOM-MG07-0009, status:valid, keywords:"daemon_state_data_dir_canonical flock_path_is_singleton_guarantee staged_handover_no_two_daemons", ocd:2026-07-07, lmd:2026-07-07] This section previously said the daemon
  state lived in an UNOFFICIAL `$HOME/.claude/janitor-global-state/` folder with
  a standing migrate-to-DATA TODO. Superseded 2026-07-07 by TRDD-2U8AH82F
  (commit ba58ebb): the DATA dir is now canonical via a staged handover. The WHY
  of the staging: the flock path IS the singleton guarantee, so a naive path
  flip would let a new-code daemon lock the NEW dir while an old daemon still
  held the LEGACY lock — two live daemons. Hence resolver-marker + copy under
  the legacy flock + NEW flock acquired BEFORE the marker (both held for the
  daemon's lifetime) + dual-read of control flags for old-code sessions.


[^11]: [id:ATOM-MG22-0003, status:valid, keywords:"marketplace_lock_path_moved last_run_stamps_not_in_data_dir control_state_vs_private_state DATA_dir_principle_exception", ocd:2026-07-22, lmd:2026-07-22, trdd:QK7M2B0X, commits:"78879d4"]
  DO NOT read this page's older claim that the marketplace lock and the per-task
  last-run stamps live in `${CLAUDE_PLUGIN_DATA}/global-state/` as current — the
  locks moved to `~/.claude/janitor-control/` in `78879d4` and the stamps are
  scheduled next, BECAUSE a lock only excludes processes contending on the SAME
  inode, so once a second chore owner (an ai-maestro server) exists, a lock it
  cannot find excludes nobody and the collision backstop silently does nothing.
  DO route by AUDIENCE — private state stays in DATA, anything a second owner
  must observe or contend on goes to the fixed control dir
  ([[janitor-fleet-control-plane]]).

[^13]: [id: ATOM-88DL-HFDJ, status: valid, supersedes: ATOM-MQ9L-E7LV, desc: "3-rung global_state_dir ladder post-TRDD-ULEGRT01 — no legacy rung, no dual-read fallback", keywords: "legacy_global-state_dir_still_read janitor-global-state_fallback 4-rung_global_state_dir_ladder current_state_locations_bullet_stale legacy_dir_tombstoned_read-fallback_EHT TRDD-ULEGRT01 era-1_legacy_retired control-flag_readers_span_only_two_locations does_the_daemon_still_read_the_legacy_global-state_folder global_state_dir_3-rung_ladder", ocd: 2026-08-28, lmd: 2026-08-28] DO NOT read the 'Current state locations' bullet's 4-rung ladder (env override -> XDG -> DATA dir once migrated-from-legacy.ts exists or on fresh install -> legacy $HOME/.claude/janitor-global-state/ while a pre-migration install awaits its daemon) or its 'Legacy dir = tombstoned read-fallback; retirement is an EHT 2 releases out' note as current, BECAUSE TRDD-ULEGRT01 already retired the legacy rung: global_state_dir() is now env override -> XDG -> the DATA dir UNCONDITIONALLY, with no legacy fallback at all, and control-flag readers (_flag_present_dual, _flag_clear_dual, read_flag_provenance, read_last_run, _generation_from_flag, _singleton_paths) span only control_dir() + global_state_dir(). DO read the legacy dir as fully RETIRED (not tombstoned-pending-an-EHT): only _legacy_global_state_dir() survives, with its sole caller migrate_global_state_to_data_dir() gated by the explicit predicate (DATA/migrated-from-legacy.ts absent) AND (legacy dir exists), never a global_state_dir()!=legacy comparison that era-1 retirement would make permanently true. SUPERSEDED BODY: (empty)

[^14]: [id: ATOM-V89R-2RUZ, status: valid, supersedes: ATOM-UZAL-KYBJ, desc: "installed-tree legacy global-state entry is RETIRED by TRDD-ULEGRT01, not a live read-fallback", keywords: "legacy_global-state_dir_still_read janitor-global-state_fallback installed_tree_diagram_stale legacy_dir_tombstoned_read-fallback_EHT retired-TRDD-ULEGRT01 legacy_dir_safe_to_remove control-flag_readers_span_only_two_locations does_the_daemon_still_read_the_legacy_global-state_folder global_state_dir_3-rung_ladder runtime_installed_tree_legacy_path", ocd: 2026-08-28, lmd: 2026-08-28] DO NOT read the installed-tree diagram's ~/.claude/janitor-global-state/ line as an active read-fallback the daemon still consults, BECAUSE TRDD-ULEGRT01 retired era-1 legacy global-state: nothing reads or writes that dir anymore except the one-time migration path on a never-migrated host, gated by the explicit predicate (DATA/migrated-from-legacy.ts absent) AND (legacy dir exists). DO treat the directory as fully RETIRED and safe for the user to remove once DATA/global-state/migrated-from-legacy.ts exists, not as a tombstoned read-fallback still consulted for version skew. SUPERSEDED BODY: (empty)
