# Changelog

All notable changes to this project will be documented in this file.

## [0.51.0] - 2026-07-17

### Bug Fixes

- Per-class capability gating — wire the server-liveness probe (TRDD-N9YAH5E7)
- Window-burn-rate alarms only in the culprit project's own sessions (token-quietness)
- Context-advisory default 60 -> 80 — one runway band below enforcement (token-quietness audit)
- Strip VIRTUAL_ENV from detached uv-script workers (TRDD-UO93APWN root cause)

### Documentation

- PZLVT2RN + X92VBFNF + H7NVKSAX shipped in v0.50.0 -> published (release 103c84a)
- Two-harness ARCHITECTURE.md rev 1 + TRDD-FENWWB4E findings ledger (plan Phase 1)
- ARCHITECTURE.md rev 2 — fold ai-maestro round 1 (per-class §2 matrix, §6 delivered contracts)
- ARCHITECTURE.md rev 3 — §6.4 factual fix (session-command verb is deployed, no verb owed)
- ARCHITECTURE.md rev 3 RATIFIED by both sides — FINAL; FENWWB4E -> todo (Phase 4 unblocked)
- FENWWB4E Phase 4 implemented -> testing (5 commits, full suite green); Phase 5 + doc pass ride v0.51.0
- V0.51.0 doc pass — findings ledger + notify channel + per-class chore gating + token-quietness (repomap regen)

### Features

- Per-project findings ledger core — record() choke point, cursor reader (TRDD-FENWWB4E)
- Wire issue_catalog.raise_issue through the findings ledger (TRDD-FENWWB4E)
- SessionStart inbox surfacing + /janitor-findings browser (TRDD-FENWWB4E)
- Daemon-to-human notification channel — tiered, severity-gated, capped (TRDD-4649ZLE0)

### Mem

- Janitor-daemon-bulk-lane — symptom-indexed page for the v0.50.0 bulk-lane fix + the lru-cache test-isolation lesson (memorize-nudge)

