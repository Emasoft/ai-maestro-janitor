# Changelog

All notable changes to this project will be documented in this file.

## [0.26.0] - 2026-07-01

### Bug Fixes

- Cache cargo target off the auto-purged macOS tempdir (clippy flake)
- Tighten 3 skill descriptions <=200 tokens + clear skillaudit/markdownlint FPs
- Trim janitor-reload-skills description under the 200-token limit

### Documentation

- Add TRDD-LQU7OXXV — /janitor-compact-context --soft and --handoff flags + /janitor-write-handoff skill
- Add TRDD-GFT33HT9 — relocate USER memory out of the auto-deleted data dir (survives uninstall)
- Standardize TRDD-ME8V2YJF list markers to clear CPV MD004 NIT (TRDD-ME8V2YJF)

### Features

- --soft/--handoff compaction, /janitor-write-handoff, /reload-skills
- Disarm/uninstall inert-guard on shipped rules + provenance orphan cleanup
- USER memory survives uninstall via a synced backup mirror (TRDD-GFT33HT9)
- Real-time token-spike + cache-miss monitor with stop-the-subagents nudge (TRDD-KI24GR5Z)
- Adaptive per-5-min baseline + anomaly detector + 5h/7d window report (TRDD-EDSFEQ5C)
- Log window-exhaustion events at rate-limits → empirical 5h/7d cap discovery (TRDD-EDSFEQ5C)
- Daemon-driven fleet disarm/pause — reach every armed session, no human (TRDD-ME8V2YJF)
- Rich disarmed-state reminder — a temporary global stop can't silently persist (TRDD-3MEUT9VW)

### Miscellaneous

- Mark reload_skills_trigger.py executable (has shebang)

