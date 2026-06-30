# Changelog

All notable changes to this project will be documented in this file.

## [0.25.0] - 2026-06-30

### Bug Fixes

- Autonomous wikimem curation OFF by default + curator off Opus (TRDD-KTP79T8P)
- Silence per-session heartbeats, not just the daemon (TRDD-NJ22HNC3)
- Gate auto-bootstrap browser behind opt-in + cap per-slot launches (TRDD-5OJX3SCF)
- Disarm/pause now DELETE the cron (self-disarm), not just silence (TRDD-RQ9FIFX6)
- Clear CPV skillaudit CROSS_TOOL_ACCESS false-positive blocking publish

### Documentation

- Mark 8UD3Q7K5 (v0.24.15) + TY2EZ8ZH (v0.24.16) published
- Record implementation commit ee26d69 for TRDD-ZGLCGC6A
- Record implementation commit 3f76b65 for TRDD-SMZFJVZ3
- Add TRDD-5OJX3SCF — OAuth auto-bootstrap surprise-browser + uncapped relaunch fix
- Mark TRDD-5OJX3SCF complete + record implementation commit b35121c
- Add TRDD-RQ9FIFX6 — disarm must STOP the heartbeat fire, not just silence
- Document disarm/pause self-disarm semantics (TRDD-RQ9FIFX6)
- Mark TRDD-RQ9FIFX6 complete + record implementation commit b3a60fd
- Add TRDD-ME8V2YJF — daemon-driven fleet disarm/pause (janitor controls all sessions itself, no human)

### Features

- Self-heal lean-ctx shell allowlist additively (TRDD-ZGLCGC6A)
- Default-ON context-size runaway guard + enforce near cap (TRDD-SMZFJVZ3)

### Tests

- Repair orphaned pre-rewrite tests (TRDD-SMZFJVZ3 follow-up)

