# Changelog

All notable changes to this project will be documented in this file.

## [0.15.0] - 2026-06-20

### Bug Fixes

- Per-session reload nudge so concurrent/fleet sessions aren't starved (TRDD-a6d2fdaf)
- Drop required_linear_history from the baseline — it jams multi-agent merges
- Degraded-rotate fallback + wider keepalive so token exhaustion never deadlocks (TRDD-a6d2fdaf)

### Documentation

- Add TRDD-a6d2fdaf — janitor plugin-update reliability (per-session reload + cache prune)
- Refresh CLAUDE.md project map — cache_prune + reload-generation + oauth degraded-rotate

### Features

- Cache-prune task — bound the plugin-cache bloat safely (TRDD-a6d2fdaf)

### Miscellaneous

- Clear 6 fixable validation warnings — exec bits + skill terminating-conditions

