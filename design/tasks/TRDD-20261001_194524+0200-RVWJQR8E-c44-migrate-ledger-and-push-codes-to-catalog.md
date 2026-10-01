---
trdd-id: RVWJQR8E
title: C44 — migrate ledger and push codes to catalog
column: blocked
status: tasked
created: 2026-10-01T19:45:24+0200
updated: 2026-10-01T19:46:34+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:24+0200
blocked-by: [JD2QR5SQ]
pre-block-column: todo
---

# C44 — migrate ledger and push codes to catalog

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C44, wave Later.

Writes (exclusive): to be set when scheduled
Task: Migrate the 29 ADVISORY, 31 ledger and 8 push codes to catalog codes. This also fixes the 24-char truncation (F8).
Verify: to be set when scheduled
Depends on: C22
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:24+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:34+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on JD2QR5SQ per DSN035UN wave order
