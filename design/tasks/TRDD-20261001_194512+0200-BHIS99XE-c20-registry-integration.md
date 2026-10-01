---
trdd-id: BHIS99XE
title: C20 — registry integration
column: blocked
status: tasked
created: 2026-10-01T19:45:12+0200
updated: 2026-10-01T19:48:10+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:12+0200
blocked-by: [2UAEQQ4A]
pre-block-column: todo
blocker-probe: [trddgrep, why, BHIS99XE]
blocker-holds-if: not-match:READY
---

# C20 — registry integration

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C20, wave W2.

Writes (exclusive): src/memory.rs
Task: Registry integration: push-site severity comes from rule(); the floors and grandfathered lists are derived from gate_floor; test every_emitted_code_is_registered; fix the F2/F16 comments
Verify: Rust gate passes; lint --no-fix output on the PROJECT memory is byte-identical before vs after, except D1's two codes
Depends on: C10
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:12+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:08+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 2UAEQQ4A per DSN035UN wave order
