---
trdd-id: VHFGPCOJ
title: C23 — strip noqa from recall output
column: todo
status: tasked
created: 2026-10-01T19:45:14+0200
updated: 2026-11-13T20:30:43+0100
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
blocked-by: []
pre-block-column: 
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
- 2026-10-08 (probe caveat, corpus sweep): this why-probe's holds-if is not-match:READY against trddgrep why output — two known ceilings: (1) a future blocker card whose TITLE contains the word READY false-unblocks this card (grep is not column-aware here); (2) the zero-open-prereq->READY transition was never observed on a flipping card (endpoints only) — trddgrep may never print READY after an archived blocker (known tooling gap). Treat a probe release as a PROMPT TO RE-VERIFY the chain, not proof of unblocked.
- 2026-11-13 — unblocked from TRDD-JD2QR5SQ (C22): proceeds on test evidence (610f569c real-binary lock+ledger, cargo 9+64 green), not field evidence; if JD2QR5SQ's field run finds a defect, re-check this card
- 2026-11-13T20:30:41+0100 — column → todo by main-agent@ai-maestro-janitor. proceeds on test evidence (610f569c real-binary lock+ledger, cargo 9+64 green), not field evidence; see TRDD-JD2QR5SQ Cleared blocked-by (--clear-blocker override).
- 2026-11-13 — note: this card writes src/memory.rs; C22 (TRDD-JD2QR5SQ) still has undecided DECISION items (C21-(c), unused-noqa label) that may also touch memory.rs; serialize, do not run in parallel with them.
