---
trdd-id: EFA4P42B
title: The injected Jev copy repeats the transcript path four times
column: complete
created: 2026-09-24T11:21:12+0200
updated: 2026-09-27T13:06:59+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T11:21:12+0200
implementation-commits: [feae6152, 8cd3d8d6, 2fe19668]
status: archived
---

# The injected Jev copy repeats the transcript path four times

Same run (E5). The injected copy prints the transcript path in the header, the elided line, the full-context line and the pointers-expand line, about 600 bytes of a roughly 3 KB budget. Acceptance: the path appears once in the injected copy, every expand instruction still works as written, and a test pins the count. Release blocker for TRDD-RAEGS1D5.

## Approval log

- 2026-09-24T11:21:12+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-24T11:42:58+0200 — column → testing by janitor-main-session. fix landed in feae6152 with a failing-first test; re-measured with the next real-transcript run
- 2026-09-27T13:06:59+0200 — COMPLETE by user. owner batch acceptance 2026-09-27 ('complete all TRDDs'); independent lean-worker verdict DONE (batch2), evidence named per box.

## Review corrections 2026-09-24

"Once" means: the path appears only in the final "pointers expand with:" trailer line; every other expand instruction refers to that command. Also, in the injected copy, an empty digest drops the "## Digest" heading and the usage line.

## Acceptance

- [x] injected copy carries the transcript path once (feae6152 in implementation-commits); pin test passes
- [x] worker re-ran the card's named tests on HEAD 2026-09-27 (batch2 report carries commands + results); owner batch acceptance 2026-09-27 ("complete all TRDDs")
