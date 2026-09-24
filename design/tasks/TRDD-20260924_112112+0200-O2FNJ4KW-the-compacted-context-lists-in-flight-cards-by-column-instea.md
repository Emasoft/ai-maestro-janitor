---
trdd-id: O2FNJ4KW
title: The compacted context lists in-flight cards by column instead of the cards the session worked
column: todo
created: 2026-09-24T11:21:12+0200
updated: 2026-09-24T11:21:12+0200
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
---

# The compacted context lists in-flight cards by column instead of the cards the session worked

Same run (E4). The fact record's in-flight list is every card in a work column: 19 cards, 17 of them stale `testing` cards, while the cards the cleared session actually worked (K0PMVRN6 in `todo`, WZKFSQ2N in `live_auditing`) are absent. The FULL copy's digest likewise leads with the STATE block of a 2026-09-05 card. The list's byte cost is not measured yet. Proposed direction (pending the advisor): order the list by relevance to the transcript (cards whose TRDD id it mentions first, most recent mention first) and cap it. Acceptance: on b2bf5b7b, K0PMVRN6 and WZKFSQ2N are listed and their STATE heads lead the digest; measured list bytes before and after are recorded; a test fails without the fix. Release blocker for TRDD-RAEGS1D5.

## Approval log

- 2026-09-24T11:21:12+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
