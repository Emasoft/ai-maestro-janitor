---
trdd-id: O2FNJ4KW
title: The compacted context lists in-flight cards by column instead of the cards the session worked
column: todo
created: 2026-09-24T11:21:12+0200
updated: 2026-09-24T11:29:46+0200
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

## Review corrections 2026-09-24

Advisor: STATE_HEAD_COLUMNS is a frozenset, so the list and the digest order vary per process (three processes gave three orders). Fix in the lane: scan the transcript once for TRDD ids, rank ALL board cards by last mention, list the top 6 with titles plus one count line for the rest, pass STATE heads only for the listed cards (least relevant first, since build_digest drops from the front), and make the column set a tuple. Mentions inside janitor-injected text (post-clear handoffs, hook output) do not count, or every card ranks equally. This supersedes the round-2 ruling "the card list is never dropped, only the titles" (decision under the owner's delegation, 2026-09-24): unmentioned cards are the board's, not the session's, and stay discoverable through the count line and trddgrep. Acceptance: WZKFSQ2N has no STATE block, so for b2bf5b7b the check is that K0PMVRN6 and WZKFSQ2N are listed and K0PMVRN6's STATE head is in the digest; the test uses a fixture transcript, not the live board.
