---
trdd-id: VHFGPCOJ
title: C23 — strip noqa from recall output
column: blocked
status: tasked
created: 2026-10-01T19:45:14+0200
updated: 2026-10-01T19:49:24+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:14+0200
blocked-by: [JD2QR5SQ]
pre-block-column: todo
blocker-probe: [trddgrep, why, VHFGPCOJ]
blocker-holds-if: not-match:READY
---

# C23 — strip noqa from recall output

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C23, wave W2.

Writes (exclusive): the recall output file per U8 (search.rs vs memory.rs; parallel with C20–C22 if U8 says search.rs)
Task: Strip noqa comments from recall output
Verify: A CLI test: a page with noqa gives recall output without it
Depends on: C02
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:07+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 622ROA5F per DSN035UN wave order
- 2026-10-01 — scope correction from C00/U8: recall output is formatted in src/memory.rs (finalize_recall ~8471, recall_one_atom ~8717, recall_one_page ~8753), so this card writes src/memory.rs and runs AFTER C22 (TRDD-JD2QR5SQ) in the memory.rs serial chain.
