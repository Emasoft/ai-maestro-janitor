# Changelog

All notable changes to this project will be documented in this file.

## [0.17.3] - 2026-06-24

### Bug Fixes

- Remove the agent-side cadence double-gate from atomize/conflict/repair (TRDD-VJ8L465M)
- Escalate a dead-but-present refresh token to the REAUTH nudge (TRDD-HJGR4I5W)

### Documentation

- Night-brain STATE — v0.17.2 shipped (memory-settings deviation-filter)
- Add TRDD-71ABD7V7 — L0 keepalive as fixed DATA-path scanned entry (SHAPE 2)
- TRDD-71ABD7V7 → dev; Phase 1 shipped (184b61c)
- TRDD-71ABD7V7 — Phase 2a shipped (closure-stager 0345000)
- TRDD-HJGR4I5W — OAuth cascade gap, dead-but-present refresh never escalates to REAUTH
- Night-brain STATE — L0 SHAPE 2 Phases 1+2a + OAuth gap (TRDD-fe45babc)
- Correct stale L0 Phase-2b file refs — old launchd files already removed (TRDD-71ABD7V7)
- Memory scheduler double-gates the cadence stamp → no-op spawns (TRDD-VJ8L465M)
- Night-brain — USER mandate to finish + harden (CPV #152 live, L0 unblocked) (TRDD-fe45babc)
- Clear MD004 lint NIT in the VJ8L465M TRDD (unblock publish --strict)

### Features

- Add L0 daemon_keepalive_entry — thin static-import entry (TRDD-71ABD7V7)
- Add closure-stager for the L0 DATA mirror (TRDD-71ABD7V7)

