---
trdd-id: B9YPSF02
title: C1B — hook timing wrapper
column: dev
status: tasked
created: 2026-10-01T19:45:07+0200
updated: 2026-10-01T19:52:46+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:07+0200
blocked-by: []
pre-block-column: 
blocker-probe: [trddgrep, why, B9YPSF02]
blocker-holds-if: not-match:READY
---

# C1B — hook timing wrapper

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C1B, wave W1.

Writes (exclusive): hooks/hook-run.sh, scripts/lib/hook_timing.py, tests/test_hook_timing.py
Task: Time each hook against its hooks.json timeout, read at runtime; write HOOK-002 at ≥80%
Verify: A scratch hook sleeping 85% of its budget gives one ledger record; a fast hook gives none
Depends on: C02
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:07+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:02+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 622ROA5F per DSN035UN wave order
- 2026-10-01T19:52:46+0200 — column → dev by main-agent@ai-maestro-janitor. Python card with no dependency on the C02 Rust scaffold (review finding 10); dispatched 2026-10-01 Cleared blocked-by (--clear-blocker override).
