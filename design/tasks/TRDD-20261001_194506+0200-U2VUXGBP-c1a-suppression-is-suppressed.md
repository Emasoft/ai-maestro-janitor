---
trdd-id: U2VUXGBP
title: C1A — suppression is_suppressed
column: blocked
status: tasked
created: 2026-10-01T19:45:06+0200
updated: 2026-10-01T19:48:06+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:06+0200
blocked-by: [622ROA5F]
pre-block-column: todo
blocker-probe: [trddgrep, why, U2VUXGBP]
blocker-holds-if: not-match:READY
---

# C1A — suppression is_suppressed

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C1A, wave W1.

Writes (exclusive): scripts/lib/suppression.py, tests/test_suppression.py
Task: is_suppressed(code,path) with family, prefix, name, per-file-ignores and expiring [[suppress]]
Verify: Unit tests; workflow-security behaviour unchanged (existing tests pass)
Depends on: C02
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:06+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:00+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 622ROA5F per DSN035UN wave order
