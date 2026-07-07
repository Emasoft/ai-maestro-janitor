---
trdd-id: ULEGRT01
title: Retire the legacy janitor-global-state read-fallback (EHT of TRDD-2U8AH82F)
column: planned
created: 2026-07-07T18:23:04+0200
updated: 2026-07-07T18:23:04+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 6
severity: LOW
effort: S
approval-tier: 0
task-type: refactor
parent-trdd: TRDD-2U8AH82F
labels: [daemon, state-migration, cleanup]
release-via: publish
test-requirements: [unit]
---

# TRDD-ULEGRT01 — Retire the legacy `~/.claude/janitor-global-state/` read-fallback

**EHT of TRDD-2U8AH82F** (staged migration to `${CLAUDE_PLUGIN_DATA}/global-state/`,
shipped in ba58ebb). The migration deliberately kept two version-skew crutches that
must be removed once the fleet has rolled forward **two releases** past the
migration release:

## Scope (all in `scripts/lib/global_state.py` + docs)

1. Remove `_legacy_read_path()` and every dual-read branch:
   `kill_switch_present`, `global_pause_present`, `maintenance_mode_present`,
   `reload_generation`, `skills_reload_generation` (revert to single-path reads).
2. Simplify the `global_state_dir()` ladder: drop the legacy rung — resolution
   becomes env → XDG → DATA dir unconditionally. Keep
   `migrate_global_state_to_data_dir()` one more release as a no-op guard, then
   delete it and its daemon.main call site together.
3. The legacy dir itself: per RULE 0 never auto-delete — surface a one-time
   drift line suggesting the user remove `~/.claude/janitor-global-state/`
   (its README-MOVED.txt explains), or fold it into `/janitor-audit`.
4. Update: README `<global-state>` note, CLAUDE.md state-locations bullet,
   `rules/janitor-footprint.md` legacy row, the 4 rules' DISARMED dual-path
   probe (drop the legacy OR-branch), and the architecture wikimem page
   (correction protocol — demote the fallback fact to a dated lesson).
5. Tests: drop the dual-read tests in `tests/test_global_state_migration.py`;
   keep the ladder + handover tests for the historical migration path until the
   function itself is deleted.

## Gate (do NOT start before)

Two published releases AFTER the release that ships ba58ebb, so every
long-running session on this machine has restarted on post-migration code.
Check: `<DATA>/global-state/migrated-from-legacy.ts` exists AND no file under
the legacy dir has an mtime newer than the marker (proves no old-code writer
is still active).

## Notes and lessons learned
