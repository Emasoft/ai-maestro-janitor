---
trdd-id: 9UORH472
title: The board fails its own validation with 70 errors over 705 cards
column: todo
status: tasked
created: 2026-10-05T23:19:48+0200
updated: 2026-10-05T23:19:48+0200
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
