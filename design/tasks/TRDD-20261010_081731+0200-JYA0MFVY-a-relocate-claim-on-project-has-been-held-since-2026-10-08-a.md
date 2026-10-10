---
trdd-id: JYA0MFVY
title: Is the relocate claim on PROJECT held since 2026-10-08 within its expiry bound or was it missed
column: verify_assumptions
status: tasked
created: 2026-10-10T08:17:31+0200
updated: 2026-10-10T08:41:41+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T08:17:31+0200
---

# A relocate claim on PROJECT has been held since 2026-10-08 and nothing expired or closed it

Seen 2026-10-10: .janitor/state/memory-maint-claimed-1791460073-1d22bb32.json, intervention relocate, scope PROJECT, stamped 2026-10-08 13:47, still in the claimed pool about 42 hours later; the file carries a report path. expire_stale_claims in scripts/memory_dispatch_claim.py is meant to expire a claim past max(caller floor, the record's own cadence times factor, 6 hours) or close it when a completion report exists. Not read: who calls expire_stale_claims and when, the relocate cadence, and whether the named report exists. TO DO FIRST: read the caller and the record's threshold, check the report file, and say whether this claim is within its bound, should have been closed on its report, or was missed. Acceptance: the claim is closed or expired by the existing path, or the defect that left it is fixed with a test.

## Approval log

- 2026-10-10T08:17:31+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T08:41:41+0200 — column → verify_assumptions. the expiry threshold is unread, so a defect is not established
