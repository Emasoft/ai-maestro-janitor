# Changelog

All notable changes to this project will be documented in this file.

## [0.14.0] - 2026-06-20

### Bug Fixes

- Gate gzip findings on inner bytes; allowlist tokenizer vocab; skip pkg-cache (#40)
- Content-exact idempotency so a same-size rule edit still refreshes (#37)
- Conflict needs a contradiction signal; aggregation skips coarse tags (#35, #38, #43)
- Repoint ai-maestro self-trigger to the shipped CLI, not the server API (#42)
- De-poison MD004 — no wrapped prose line may start with '+ '
- Install SIGTERM handlers before publishing the pid file (startup race)

### Documentation

- Memory-index re-architecture (A/B/C + overview + #49) SHIPPED in v0.13.0; gated re-enable remains (TRDD-a5780c23)
- Memory-system page — index is memgrep-only (MEMORY.md retired) + overview + harvest (TRDD-a5780c23)
- Refresh CLAUDE.md project map — harvest skill, memgrep overview, body-fidelity verify (v0.13.0)
- Gated re-enable DONE — wikimem editor live on v0.13.0 (TRDD-a5780c23)
- Daily memory-system migration — staggered harvest + gitignore enforcer (TRDD-3f7b6807)
- Daily-migration P1+P2+P3(LOCAL) done; PROJECT scope surfaced (TRDD-3f7b6807)
- Metadata.type is organizational-only, not retrieval-affecting (#46)
- Refresh CLAUDE.md project map for v0.14.0 — memgrep lint, librarian/scanner fixes

### Features

- Per-project phase staggering for editor cadences (TRDD-3f7b6807)
- PROJECT-memory gitignore-exception enforcer (TRDD-3f7b6807, Phase 2)
- Auto-recall hook ON by default with a triviality guard (#45)
- Add 'lint' subcommand — deterministic note-integrity gate (#47)

### Tests

- Widen detached-worker wait to de-flake the full suite

