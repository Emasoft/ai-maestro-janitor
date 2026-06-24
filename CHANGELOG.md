# Changelog

All notable changes to this project will be documented in this file.

## [0.18.1] - 2026-06-24

### Bug Fixes

- Refresh-retry a locally-expired alternate before excluding it (TRDD-1IKF0A6D)

### Documentation

- L0 keepalive published (v0.18.0) + night-brain TIER-1-complete/wind-down (TRDD-71ABD7V7, TRDD-fe45babc)
- GROUP C C1 self-integrity manifest SHIPPED in v0.18.0 (TRDD-53a00e44)
- Add the L0-L3 immortality model to the architecture hub (TRDD-324223a6)
- Refresh CLAUDE.md project map for the v0.18.0 immortality files
- Scheduler cheap content-precheck to kill ~240k no-op memory spawns (TRDD-3XS3PDCF)
- Night-brain STATE — resume after wind-down, 6 pieces committed (TRDD-fe45babc)
- Night-brain STATE — 3XS3PDCF split content-precheck landed (441d467), still holding
- Harvest precheck is BLOCKED on in-flux harvest behavior, not merely deferred (TRDD-3XS3PDCF)
- Refresh CLAUDE.md project map — add memory_content_precheck module
- Correct 3XS3PDCF publish-deferral WHY — release-risk, not budget (TRDD-3XS3PDCF)
- Add TRDD-1IKF0A6D — cmd_auto refresh-retry locally-expired alternate (RENEW residual)

### Performance

- Split content-precheck so a cadence-due-but-empty scheduler no longer spawns a 240k no-op agent (TRDD-3XS3PDCF)

