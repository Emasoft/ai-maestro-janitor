---
trdd-id: 7SMPCPNT
title: C12 — noqa parser
column: blocked
status: tasked
created: 2026-10-01T19:44:48+0200
updated: 2026-10-01T19:48:00+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:44:48+0200
blocked-by: [622ROA5F]
pre-block-column: todo
blocker-probe: [trddgrep, why, 7SMPCPNT]
blocker-holds-if: not-match:READY
---

# C12 — noqa parser

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C12, wave W1.

Writes (exclusive): src/noqa.rs
Task: Parse line and page noqa plus frontmatter lint-ignore; report matched/unmatched; blanket detection
Verify: Unit tests: each form, multiple codes, blanket, unmatched
Depends on: C02
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:44:48+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:45:45+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 622ROA5F per DSN035UN wave order
