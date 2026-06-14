# Changelog

All notable changes to this project will be documented in this file.

## [0.8.0] - 2026-06-14

### Bug Fixes

- USER scope → ${CLAUDE_PLUGIN_DATA}/memory (not ~/.claude/memory)
- USER scope resolves to the janitor's FIXED data dir, never ${CLAUDE_PLUGIN_DATA}
- Zsh-safe array form for recall ROOTS — was silently returning 0 hits on zsh
- Scope doc-lint out of the memory corpus + all TRDD-lifecycle folders
- Make bootstrap skill CPV-clean (only the .claude/ gitignore FP #120 remains)
- User-scope wins — no redundant project-local rule copies (issue #36)
- Clear CPV CRITICAL+MINOR on the env-report script

### Documentation

- Complete #172 — PRRD silver rules, 4-zone design folders, v1→v2 TRDD migration
- Close f892e109 STATE — resolve stale "DECISION PENDING" vs complete
- Add TRDD-4c3733d9 — memory scope storage locations (3-scope redesign)
- Install PROJECT-scope wikimem pages + 8 promoted notes (.claude/project/memory)
- Close TRDD-4c3733d9 — memory scope redesign complete (all phases + tested)
- Record CPV #120 .claude/ gitignore FP (PROJECT scope)
- Add TRDD-db169d9e — janitor portability + context-awareness
- Answer D3 (ai-maestro send-to-terminal API) by research — TRDD-db169d9e

### Features

- PROJECT scope → <repo>/.claude/project/memory (namespaced, collision-proof)
- Proactive-use directives + /janitor-memory-bootstrap (fleet rollout)
- Context-gate + process-ancestry terminal detection (TRDD-db169d9e Phase 1)
- Gate TRDD-framework detectors on the ai-maestro context (TRDD-db169d9e Phase 2)
- Exclude the ai-maestro fleet from daemon auto-update (TRDD-db169d9e Phase 3)
- Terminal-aware self-trigger send-abstraction + tmux backend (TRDD-db169d9e Phase 4)
- Ai-maestro API send + subprocess gate-test harness (TRDD-db169d9e Phase 5)
- /janitor-identify-environment — full runtime-environment report
- R5 user-level-only — install-scope detector + arm refusal (TRDD-db169d9e Phase 6, COMPLETE)

### Miscellaneous

- Refresh after memory-system build (bootstrap skill + scope migration)
- Close TRDD-8546a187 — baseline reconcile shipped v0.7.0 (#157)

### Tests

- Tighten gh-stub to method->path routing semantics (NIT #182)

