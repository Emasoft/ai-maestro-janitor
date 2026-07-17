# Changelog

All notable changes to this project will be documented in this file.

## [0.48.0] - 2026-07-17

### Bug Fixes

- Re-stamp the live-identity beacon when the credential changes (TRDD-6AABK2BG)

### Documentation

- EQ792YPX shipped v0.47.0 -> published; spin out restart EHT TRDD-2C8XFOW9 (blocked on ai-maestro#75 + user confirm)
- 2C8XFOW9 architecture correction — settings-enforce+restart is a DAEMON global command (#N standalone daemon vs #J server-as-daemon, no agent-group overlap)
- Refresh CLAUDE.md project map (v0.47.0 — settings_ensurer + global_state.settings_ensurer_lock)
- Add TRDD-6AABK2BG — a stale live-identity beacon blinds proactive rotation
- Fix MD018 markdownlint NIT — no wrapped line starts with '#75'

