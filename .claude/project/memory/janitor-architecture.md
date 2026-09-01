---
name: janitor-architecture
description: "how does the ai-maestro-janitor work / what runs the drift detectors / where does janitor state live / why a daemon AND a heartbeat / how does it survive a freeze or crash / what makes it immortal (the L0-L3 keepalive + watchdog layers) / what is the scope invariant / which detector finds X / where are the pattern libs — the architecture overview hub / a session stayed dead after a compaction / resume-after-compact flag never consumed / why does CLAUDE_PLUGIN_ROOT get wiped on every update / where should persistent state be written / what is the ONE SANCTIONED EXCEPTION folder ~/.claude/janitor-control / why must user/global-scope operations go through the daemon only / what is the runtime installed tree layout / how does the janitor decide project-scope vs user-scope for a given operation / the kill-switch came back after janitor-global-arm / the janitor disarmed itself again for no reason / a cleared STOP was resurrected by the migration / which code still touches the legacy janitor-global-state dir / is the legacy janitor-global-state dir safe to delete / arm did not stick on an un-migrated host"
ocd: 2026-06-13
lmd: 2026-09-01
metadata:
  node_type: memory
  type: project
  tier: hub
  globs:
    - "scripts/**"
    - "skills/**"
    - "CLAUDE.md"
    - "design/requirements/PRRD.md"
publish-globally: false
split-lineage: 959060b8fb99469c8afe79d502cf3dac
---

# ai-maestro-janitor — architecture hub

The janitor is a Claude Code plugin **with no main agent** that keeps the dev
environment tidy and secure. It runs as two cooperating tiers: a **per-session
heartbeat** that surfaces project-scoped drift to the model, and **one
machine-wide daemon** that owns every user/global-scope mutation. This page is
the navigable prose layer over the auto-generated project map in `CLAUDE.md` —
read this to understand *how the pieces fit*, then drop into `CLAUDE.md`'s
fenced map for the exact file/symbol index. [^1]

^ATOM-EXPB-DEFP [desc: "TRDD-ULEGRT01 retired the legacy global-state dir — no dual-read, no 4th ladder rung, migration gated by an explicit predicate", keywords: legacy_global-state_dir_still_read janitor-global-state_fallback kill-switch_at_legacy_path_ignored 4-rung_global_state_dir_ladder migration_self-neutered_after_retiring_rung_4 dual-read_legacy_for_version_skew TRDD-ULEGRT01 era-1_legacy_retired control-flag_readers_span_only_two_locations does_the_daemon_still_read_the_legacy_global-state_folder global_state_dir_3-rung_ladder legacy_global_state_dir_sole_caller_migration, ocd: 2026-08-28, lmd: 2026-08-28]

DO NOT read control-flag readers as dual-reading the legacy `$HOME/.claude/janitor-global-state/` for version skew, or that dir as a tombstoned read-fallback pending an EHT, BECAUSE TRDD-ULEGRT01 retired era-1 legacy global-state entirely: `global_state.py::global_state_dir()` is now a 3-rung ladder (`$JANITOR_GLOBAL_STATE_DIR` env override -> `$XDG_STATE_HOME/janitor` -> the plugin DATA dir `${CLAUDE_PLUGIN_DATA}/global-state/` UNCONDITIONALLY, no 4th legacy rung), and every control-flag reader (`_flag_present_dual`, `_flag_clear_dual`, `read_flag_provenance`, `read_last_run`, `_generation_from_flag`, `_singleton_paths`) now spans only TWO locations — `control_dir()` and `global_state_dir()` — never the legacy path. DO read the legacy dir as RETIRED: `_legacy_read_path()` was deleted; only `_legacy_global_state_dir()` survives, with its sole caller `migrate_global_state_to_data_dir()` gated by the explicit predicate `(DATA/migrated-from-legacy.ts absent) AND (legacy dir exists)` — deliberately NOT a `global_state_dir() != legacy` comparison, which era-1 retirement would make permanently true and silently neuter the migration. [^15]

## Parts map

This page is the entry point; the detail lives in three sub-pages (split from
this page on 2026-09-01 — it had outgrown a single load). Each still carries
its own lessons-learned section and links back here.

## Applies to

- [[janitor-architecture-control-flow]] — the two heartbeat/daemon tiers, the
  full `dispatch.py` control flow, the full/maintenance/stop heartbeat modes,
  the scope invariant (HARD RULE — issue #7), and self-healing across both
  respawn paths (stub + OS keepalive).
- [[janitor-architecture-detectors-and-resilience]] — the full detector
  roster by function, the pattern-library layout, the skills roster, the
  resilience pillars (file integrity, the Tier-1 OOM guard, self-integrity),
  and the L0-L3 immortality/self-resurrection layers.
- [[janitor-architecture-state-and-conventions]] — the filesystem & state
  conventions table, the ONE SANCTIONED EXCEPTION
  (`~/.claude/janitor-control/`), the PRRD rule pointers, and the legacy
  `janitor-global-state/` retirement history.

## See also

- [[window-burn-rate-alarm-contract]] — the four gates a burn trip must pass
  (including the idle gate), why every usage figure names its account and its
  sample age, and why the `usage_probe` cache retires entries the access-token
  rotation strands.
- `CLAUDE.md` — the auto-generated, always-current project map (file → symbol
  index) this hub narrates. When the structure changes, the map is the source
  of truth; reconcile this prose to it.
- `design/requirements/PRRD.md` — the project's golden/silver rules.
- LOCAL scope — anything machine-specific (the host's actual global-state path,
  the OAuth rotator's account/keychain particulars, absolute home paths) lives
  in LOCAL-scope notes, NOT here. This page is git-tracked and host-global, so
  it stays generic by design. [^2]
- LOCAL-scope notes `reference_maintenance_mode_cache_warm_vs_disarm` and
  `feedback_arming_one_session_wakes_the_whole_fleet` — the maintenance-mode
  cost model and the fleet-wake incident that motivated it.
- [[janitor-keepalive-test-isolation-fsevents]] — the L0 keepalive's call-time
  state resolution, the test-isolation levers (`JANITOR_GLOBAL_STATE_DIR` /
  `JANITOR_DATA_DIR`, not `CLAUDE_PLUGIN_DATA`), and the bounded restage — the
  fseventsd-runaway class (TRDD-ZNN0UK5K).
- [[janitor-fleet-guardian-reachability]] — why the status table's `armed` column
  is not "the heartbeat is running", why `/janitor-global-arm` arms nothing, and
  why the launchd daemon logged `UNREACHABLE ({})` for 254 beats (stripped PATH
  for tmux; no TCC Automation grant for iTerm). The counterpart to the
  Immortality section above: the OS-keepalive bought the guardian durability and
  cost it its injection channels.

- [[janitor-fleet-control-plane]] — the fixed `~/.claude/janitor-control/`
  directory: what moves there and why the scope rule is AUDIENCE, plus the
  dual-LOCK (not dual-READ) migration a coordination lock requires.

- [[three-pillars-rules-ownership]] — which repo owns each TRDD/PRRD/kanban
  rule file, the pinned `aimaestro-*` overlay names, and the user-scope
  orphans that make an agent read two generations of one rule.

- [[janitor-daemon-handover-unowned-chores]] — what happens to the two tiers
  above when a live ai-maestro server owns the host: §7.2 withdraws the whole
  daemon, so the six chores nobody absorbed belong to nobody.

- [[janitor-daemon-process-identity]] — WHICH interpreter the daemon runs under
  and why macOS TCC cares, plus the restart gate that evicted our own
  version-less daemons every fire and the breaker that quarantined a healthy
  version for it.
- [[janitor-two-runtime-backends]] — the #N standalone vs #J harness backend
  split, the ai-maestro boundary IRON RULE (scripts only, never the HTTP API).
- [[janitor-findings-pipeline]] — the findings-ledger choke point + the
  daemon-only human notification channel.
- [[janitor-core-files-reference]] — the file-by-file reference for
  `scripts/` and `scripts/lib/` core modules.
- [[git-index-lock-orphan-recovery]] — recovering an orphaned `.git/index.lock`
  left by a killed writer, and why every guard there fails closed.
- [[janitor-detector-and-hook-roster]] — the full 39-detector / 16-hook
  grouped roster behind this hub's abbreviated summaries.
- [[janitor-gh-reply-monitor]] — the GH-REPLY MONITOR subsystem (replies to
  threads this project opened, on any repo).
- [[janitor-skills-and-agents-roster]] — the full skills control-surface +
  the two single-curator agents.


## Notes and lessons learned

[^1]: [id:ATOM-MG07-0006, status:valid, keywords:"hub_is_prose_overlay_not_second_copy auto_map_wins_structural_disagreement fix_prose_not_map", ocd:2026-06-13, lmd:2026-06-13] This hub is the prose overlay of the
  fenced `CLAUDE.md` repomap, not a second copy of it. The map enumerates files
  and symbols and is regenerated automatically; this page explains the *why* and
  the *flow* a contributor needs before reading the map. If the two ever
  disagree on a structural fact, the auto-generated map wins and this prose is
  the thing to fix.


[^2]: [id:ATOM-MG07-0007, status:valid, keywords:"project_user_page_no_machine_private_data no_home_path_email_token_hostname memory_scope_leak_invariant", ocd:2026-06-13, lmd:2026-06-13] PRIVACY: a PROJECT/USER wikimem page is
  git-tracked and host-global, so it MUST NOT carry machine-private data — no
  `$HOME`-expanded absolute paths, no account emails, no OAuth tokens, no
  hostnames. The daemon's real global-state directory, the rotator's account
  details, and any absolute home path are therefore only *named* here as "lives
  in LOCAL scope" and documented generically with `$HOME` / `<repo-root>` /
  `<email>`. The janitor's own `memory-scope-leak` detector polices exactly this
  invariant on the PUSHED memory scope.


[^15]: [id: ATOM-08C7-MBBL, status: valid, desc: "TRDD-ULEGRT01: era-1 is retired for READS only — the clear, the migration and the keychain latch still touch the dir", keywords: "kill-switch_came_back_after_janitor-global-arm the_janitor_disarmed_itself_again_for_no_reason cleared_STOP_resurrected_by_the_migration legacy_global-state_dir_is_still_being_written_to nothing_reads_janitor-global-state_is_wrong _flag_clear_dual_legacy_unlink migrate_global_state_to_data_dir_copied_a_cleared_flag retiring_a_read_path_silently_broke_the_clear is_the_legacy_janitor-global-state_dir_safe_to_delete which_code_still_touches_janitor-global-state _legacy_keychain_latch_path_still_reads_legacy arm_did_not_stick_on_an_un-migrated_host", ocd: 2026-08-28, lmd: 2026-08-28] DO NOT read "the legacy dir is retired" as "nothing touches it", BECAUSE three deliberate accesses survive — the one-time migration reads it, _flag_clear_dual still UNLINKS there, and safe_storage::_legacy_keychain_latch_path reads the keychain latch; the clear is load-bearing, since dropping it lets migrate_global_state_to_data_dir() copy a just-cleared kill-switch forward and silently undo /janitor-global-arm on an un-migrated host. DO audit WRITE and DELETE paths separately whenever you retire a READ path — "where I look" and "where I must not leave anything" are different questions.
