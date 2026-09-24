---
trdd-id: O2FNJ4KW
title: The compacted context lists in-flight cards by column instead of the cards the session worked
column: testing
created: 2026-09-24T11:21:12+0200
updated: 2026-09-24T13:39:35+0200
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
implementation-commits: [873a103b, fdf2de09, 687d3dd0, ad8a82b6]
---

# The compacted context lists in-flight cards by column instead of the cards the session worked

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-24

- 2026-09-24 13:38 — column testing. Landed: 873a103b (the cards the session worked are listed first, top 6 with titles; every other open id is named on one capped line), fdf2de09 (a tool_use block naming more than 3 open ids does not count; bare ids are matched against the open-card set; the other-cards line is its own section), 687d3dd0 (the same more-than-3-ids cap for assistant text blocks; owner messages stay uncapped). ad8a82b6 pins the cap at its exact boundary with 4 mutant-proven tests. Known limit (the CURRENT rule, not a requirement): a genuine assistant sentence naming 4 or more cards counts none of them. On real sessions b2bf5b7b and accccb8b, 687d3dd0 dropped one 8-card assistant block but left the top 6 unchanged: harmless, benefit unproven on real data.
- NEXT: row V11 of TRDD-DQXMND59 on the final tree and the full suite; then close.

Same run (E4). The fact record's in-flight list is every card in a work column: 19 cards, 17 of them stale `testing` cards, while the cards the cleared session actually worked (K0PMVRN6 in `todo`, WZKFSQ2N in `live_auditing`) are absent. The FULL copy's digest likewise leads with the STATE block of a 2026-09-05 card. The list's byte cost is not measured yet. Direction: see Review corrections below. Acceptance: see Review corrections below. Release blocker for TRDD-RAEGS1D5.

## Approval log

- 2026-09-24T11:21:12+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-24T13:29:18+0200 — column → dev by janitor-main-session. 873a103b and fdf2de09 landed; the assistant-text cap (F3) is uncommitted, so the card is in dev, not todo
- 2026-09-24T13:37:27+0200 — column → testing. all three commits landed (873a103b, fdf2de09, 687d3dd0); verification is V11 of TRDD-DQXMND59 on the final tree plus the full suite

## Review corrections 2026-09-24

Advisor: STATE_HEAD_COLUMNS is a frozenset, so the list and the digest order vary per process (three processes gave three orders). Fix in the lane: scan the transcript once for TRDD ids, rank ALL board cards by last mention, list the top 6 with titles, then every other open card id (in-flight, todo and blocked) on one line without titles (every pending card stays named, as the owner's directive on TRDD-WZKFSQ2N requires, and the round-2 "every id kept" ruling still holds; only titles and STATE heads are dropped), pass STATE heads only for the listed cards (least relevant first, since build_digest drops from the front), and make the column set a tuple. Mentions inside janitor-injected text (post-clear handoffs, hook output) do not count, or every card ranks equally. The ordering and the heads change; no card id is dropped. Acceptance: WZKFSQ2N has no STATE block, so for b2bf5b7b the check is that K0PMVRN6 and WZKFSQ2N are listed and K0PMVRN6's STATE head is in the digest; the test uses a fixture transcript, not the live board.
Measured on b2bf5b7b: the top 6 are the cards that session worked (K0PMVRN6, WZKFSQ2N, FWDZDB7W, 4XND73XD, ADIGRD0T, RAEGS1D5). Correction to 873a103b's message: the ids part of the other-cards line is capped at 300 bytes and the whole line is about 340; on the current board the cap is always hit, so the line names as many ids as fit and counts the rest. Follow-up in flight: a tool_use input naming more than 3 open ids does not count, bare ids are matched against the open-card set, and the line gets its own section instead of travelling as a finding.
Correction to the O2FNJ4KW worker's "in-flight fallback fill" explanation (review of fdf2de09): BLGZTHQ9 and U6C3YXEL appeared in the listed cards because they are todo cards the transcript mentions (likely in prose), not because a fallback filled empty slots. Verified 2026-09-24 in the source: all 4 HandoffInputs constructors (summarize_previous_session.py x3, on-session-start-post-clear-compact.py x1) pass other_open_ids, and the template renders it.
The follow-up above landed in fdf2de09 (a tool_use input naming more than 3 open ids does not count, bare ids are matched against the open-card set, the other-cards line is its own section). The same >3-distinct-open-ids cap for ASSISTANT text blocks (owner messages stay uncapped) is F3: scripts/lib/jev_compaction_lane.py + tests/test_summarize_previous_session.py, verified by its worker (reports/compaction-replacement/20260924_130950+0200-F3-lane-worker.md) and landed as 687d3dd0 on 2026-09-24 (its comment's line citations into jev_compaction.py and jev_compact.py were replaced by symbol names first, because two were already wrong).
ad8a82b6 adds 4 cap-boundary tests, each mutant-proven (reports/compaction-replacement/20260924_133757+0200-f3-tests.md). 687d3dd0 measured on real sessions b2bf5b7b and accccb8b: it drops one 8-card assistant block, but the top 6 cards are unchanged, so no ranking effect was observed on the sessions measured; the fix is harmless but its benefit is unproven on real data. The 3-counts / 4-counts-none cliff is the CURRENT rule (a disclosed limitation), not a requirement.
