# Changelog

All notable changes to this project will be documented in this file.

## [0.50.0] - 2026-07-17

### Bug Fixes

- Self-cancel when nothing is pending (TRDD-8IZ8COQ8)
- Per-project channeling — no automatic surface carries another project's findings (TRDD-X92VBFNF)
- Background bulk lane — never starve the 60s survival beats (TRDD-H7NVKSAX)

### Documentation

- 28XF77X6 complete -> published (v0.49.1 shipped)
- Add TRDD-4649ZLE0 — daemon-to-human notification channel (user directive: findings must reach a human when no session is alive)
- H7NVKSAX record implementation commit 0bbd2ff
- Two-backend architecture section + README harness note + repomap refresh (TRDD-PZLVT2RN Phase E)
- PZLVT2RN — rewrap NEXT ACTION so no line starts with '#100' (markdownlint MD018 NIT-blocked the strict gate, same class as 3fde74d)

### Features

- The two-world backend SSOT — harness_backend.py (TRDD-PZLVT2RN Phase A)
- Harness-exclusion — never actuate on a server-owned ai-maestro agent (TRDD-PZLVT2RN Phase B)
- \#J thin mode — no daemon, no outside-world writes inside an ai-maestro agent (TRDD-PZLVT2RN Phase C)
- Yield once-only chores to an active ai-maestro server (TRDD-PZLVT2RN Phase B2)
- \#J delegation + self-trigger hardening (TRDD-PZLVT2RN Phase D)

