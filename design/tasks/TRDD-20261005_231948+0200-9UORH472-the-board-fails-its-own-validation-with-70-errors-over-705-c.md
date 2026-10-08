---
trdd-id: 9UORH472
title: The board fails its own validation with 70 errors over 705 cards
column: todo
status: tasked
created: 2026-10-05T23:19:48+0200
updated: 2026-10-08T19:21:26+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T23:19:48+0200
---

# The board fails its own validation with 70 errors over 705 cards

Goal: investigate each error card by card and repair or re-column it; never by a scripted sweep. MEASURED 2026-10-05 by one run of the card tool's validate (report 20261005_231015 fork-dedupe-keys-and-small-anomalies, section 4, which lists every card): 70 errors and 646 warnings. Errors by rule: 13 cards complete but still in the tasks folder with unchecked boxes; 13 terminal without a checklist; 11 blocked with no runnable probe; 7 blockers that are not card ids (five of them cross-project references cut to 8 characters on 2C8XFOW9, 6054NY8H, RSSN9A0P, 9ZPU69UC and POA0157J, and one human decision on QHACQPPG); 3 blockers that are already terminal; 2 cards with two parents; 2 body state claims; and one each of a completed card with an unfinished prerequisite (SLFMG704), a mandate issued below the card's floor (66EMACDD), a completed card with an open child (ULEGRT01), a missing parent (924645BB) and a dangling superseded-by (YXY992BN). Open question to settle first: how a wait on a human decision is written so the tool accepts it; on QHACQPPG emptying blocked-by only traded the error for blocked-without-blocker, and the tool names a blocker-probe field that was not tried. From a fork's report; the session did not re-run the validation.

## Approval log

- 2026-10-05T23:19:48+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Corrections

2026-10-05 (review): the list in the body does not add up to 70 as written. The 13 cards that are complete but still in the tasks folder carry two errors each (the folder mismatch and the open boxes), and the blockers that are not card ids are 7 rows over 6 cards (9ZPU69UC has two). This card is an umbrella, not one atomic task: each repair is a per-card judgment recorded on that card, the tool's automatic fix is never looped over the list, and a move of a card between lifecycle folders is decided card by card. The question of how a wait on a human decision is written belongs to the card tool, which is another project's.
2026-10-08: citation-sweep round closed. Correction to the sweep commit's message ('every fix independently re-verified'): the count was 5 of 6 at commit time — index.rs:2162 was trusted to the worker's grep and the follow-up check found it off (the fn at :2162 is a DIFFERENT test, an_index_behind_the_ladder_is_not_a_failed_migration; the half-applied-migration test is a_migration_that_fails_validation_rolls_back_and_does_not_stamp_its_version at index.rs:2059). Fixed to symbol+line. Lessons per review round 10: a verification claim in a commit message must name its own coverage; bare line numbers rot (the sweep found +57/+38/+40 drift) — symbol+line is the durable shape for future checklists.
2026-10-08 round 11: the round-10 note's deltas wording corrected — the +57/+38/+40 numbers were derived by the round-10 review FROM the sweep's old→new pairs, not found by the sweep itself; provenance now stated. And the 053SGT7N paraphrase was settled by reading both test bodies (round-11 detail on that card).
2026-10-08 (B14 terminal-closure COMPLETE): all 12 complete-column cards + wikimem quartet + grandfathered 4334AAD0 audited (open-box reports reports_dev/b14-openbox-audit-a.md/-b.md), boxes ticked with evidence or struck with supersession reasons, archived — 16 archived this pass. Blocker probes added to 16 parked cards (trdd/issue/decision/date forms, fail-closed canaries). Remaining validate ERRORs: 5, ALL on immutable archived cards (DANGLING-REF YXY992BN, ORDER-NPT-VIOLATED SLFMG704, BODY-STATE-CLAIM HMLS5WE8, MANDATE-FORGED 66EMACDD + UHMB7BZW) — unfixable in place per TRDD-MQE5D28T D8; recorded as known-noise. LFSWY0C6 parked in blocked on the owner's editorial-layer-split decision.
