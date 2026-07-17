# Changelog

All notable changes to this project will be documented in this file.

## [0.49.0] - 2026-07-17

### Bug Fixes

- Stop the infinite compact loop — floor gate + 350k threshold (TRDD-D3PROACT)

### Documentation

- Add TRDD-D3PROACT — proactively compact an idle large context to prevent the cold burn
- Add TRDD-CCCOMPAT — align the janitor with Claude Code through 2.1.212
- Refresh CLAUDE.md project map (D3PROACT + CCCOMPAT symbols)
- D3PROACT — record the infinite-compact-loop finding + 4 lessons; refresh map
- Wikimem — the compaction floor gate and why a size-only gate can't terminate
- Record implementation-commits for the batch; QW6RVAKN dev -> published

### Features

- Proactively compact an idle large context to prevent the cold burn (TRDD-D3PROACT)
- Accept CC's integer env-var spellings (1e6, 64_000) in config knobs (TRDD-CCCOMPAT)
- Compact a large idle context at Stop — the event that CAN beat the burn (TRDD-D3PROACT)

