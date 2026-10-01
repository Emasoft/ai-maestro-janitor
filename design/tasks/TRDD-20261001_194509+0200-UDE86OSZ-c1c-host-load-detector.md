---
trdd-id: UDE86OSZ
title: C1C — host-load detector
column: blocked
status: tasked
created: 2026-10-01T19:45:09+0200
updated: 2026-10-01T19:46:04+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:09+0200
blocked-by: [622ROA5F]
pre-block-column: todo
---

# C1C — host-load detector

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C1C, wave W1.

Writes (exclusive): scripts/detectors/host-load.py, tests/test_host_load.py
Task: os.getloadavg() above cores×4 gives a HOST-001 line; not yet registered
Verify: Unit test with an injected load value
Depends on: C02
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:09+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:04+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 622ROA5F per DSN035UN wave order
