---
trdd-id: ZXKJZLZK
title: The hard handoff path loses its urgency because the chained compact trigger runs without hard so guard 2 can skip it
column: backburner
created: 2026-09-18T06:22:32+0200
updated: 2026-09-18T06:36:23+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-18T06:22:32+0200
---

# The hard handoff path loses its urgency because the chained compact trigger runs without hard so guard 2 can skip it

Symptom — /janitor-compact-context --handoff --hard is the emergency path, and guard 2 exempts --hard for exactly that reason, but the compact it finally sends can still be skipped by guard 2. Mechanism — compact_trigger.py --hard --handoff sends ESC then /janitor-write-handoff --then-compact; that skill's step 3 runs compact_trigger.py WITHOUT --hard (deliberately soft: an ESC there would interrupt the handoff turn itself); guard 2 in compact_trigger.py exempts only args.hard, so the chained call is guarded and can print GUARD2_HARNESS_IMMINENT and send nothing. Introduced with guard 2 in commit 73254e33 (TRDD-PH8SAQKS). Options — (a) a flag that skips guard 2 without an ESC, passed by the chain; (b) pass --hard in the chain, after checking what its ESC does to the ending handoff turn; (c) keep the guard and only surface the skip to the user (the interim B3 wording). Open question for the user: which.

## Approval log

- 2026-09-18T06:22:32+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-18T06:36:15+0200 — column → backburner. design column means the design is being written in place; this card awaits a user decision, like its sibling K0BIY8K2
- 2026-09-18T06:36:21+0200 — correction: minted by a janitor-main-session worker under the user's general go-ahead, not a mandate for this specific card; the 06:22:32 MANDATE line was the tool's default attribution.
