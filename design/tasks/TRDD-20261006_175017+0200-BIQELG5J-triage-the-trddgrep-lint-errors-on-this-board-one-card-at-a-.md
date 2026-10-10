---
trdd-id: BIQELG5J
title: Triage the trddgrep lint errors on this board one card at a time
column: human_review
status: tasked
created: 2026-10-06T17:50:17+0200
updated: 2026-10-10T23:19:12+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T17:50:17+0200
---

# Triage the trddgrep lint errors on this board one card at a time

Requested by the ai-maestro hub session (2026-10-06 self-review). trddgrep lint exits 1 with errors including MANDATE-FORGED x1, ZONE-MISMATCH x13, GRAPH-FALSE-COMPLETE x4, TERMINAL-WITH-OPEN-BOX x17, TERMINAL-WITHOUT-CHECKLIST x69, LEGACY-REFUSED-FOLDER (3 cards in design/refused/). Per-card judgment, never a mass script; cards entered on or before 2026-08-23 are grandfathered under 3P-KAN-21. Start with MANDATE-FORGED and ZONE-MISMATCH. NEXT ACTION: run trddgrep lint --rule MANDATE-FORGED and read that card.

## Approval log

- 2026-10-06T17:50:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T23:19:12+0200 — column → human_review. 7 of 12 lint errors fixed; the other 5 sit on archived cards and need a tool change in another repository, draft on the card

## STATE

2026-10-06 NEXT ACTION: run trddgrep lint --rule MANDATE-FORGED and read that card.
2026-10-10 23:25 TRIAGED (TRDD-S6GX1DHN wave 22 card 3). The lint of 2026-10-06 named 107 errors; today it named 12 (829 cards scanned), and 5 remain. FIXED, 7. (a) BLOCKED-WITHOUT-PROBE on 5 parked cards, each given a probe that was run once from the card text. 1T9034NC asks gh for the state of Emasoft/ai-maestro issue 173 (printed OPEN). OEGPT048 lists the daemon keepalive error log only when it is over 5 MB (printed nothing; with a size of 0 as control it listed the file). VN2ASDKJ counts tick-stalled in the two daemon logs (0 and 0). GLDLS7UM lists the cached janitor versions and holds until one above 3.8.11 appears (the first idea, find -newer, was dropped because folder times do not follow version order). 2O7JA0TG prints LONGGAP when a clear logged in this project after 2026-10-10 22:40 has no heartbeat fire within 45 minutes (printed NOGAP; with the date floor at 0 it printed LONGGAP for the known old gaps). LIMITS of these probes. Nothing runs them, so each is a recipe for whoever re-reads the card. The VN2ASDKJ probe sees only the roughly 39 hours the daemon log keeps. The 2O7JA0TG probe cannot tell a closed session from a live one, so LONGGAP is a prompt to look and not a verdict, and it reads project logs that rotate. The GLDLS7UM probe shows a newer version exists, which is needed for its acceptance event and is not that event. Its pattern begins with a line anchor and needs a multi-line match. (b) TERMINAL-WITHOUT-CHECKLIST on U119W52S and 8524H5V1. Each was moved to testing, given an Acceptance section drawn from its own closing record, and moved back to complete. No new test was run for either. One box on 8524H5V1 says its claim was not re-read; it was read right after (host-load at scripts/dispatch.py line 514, HOST-002 in the line built at scripts/lib/daemon_runaway.py line 356).
NOT FIXED, 5, all on archived cards, which this board treats as immutable. 66EMACDD and UHMB7BZW (MANDATE-FORGED) are superseded cards whose floor is the user and whose mandate was written by the main agent (mandated-by manager on the first, none on the second, with approved false). SLFMG704 (ORDER-NPT-VIOLATED) was completed on 2026-08-02 while its prerequisite I6ZZWVDN was open; that card is in backburner today, so the error clears only if it closes. YXY992BN (DANGLING-REF) names as its successor agentlenspro-investigate-burn, which is work in another project and not a card; the tool has no spelling for that, the same gap as TRDD-SUUDAXRT. HMLS5WE8 (BODY-STATE-CLAIM) is flagged on line 155, a sentence that narrates its past column moves; read as history it is a false positive. The lint already lowers the two checklist rules to a warning on archived cards because an error nobody may fix keeps the corpus red (lib/trdd-doctor.ts, the comment marked G8); these four rules do not. That is a request for the tool, which belongs to the ai-maestro repository, where open issue 170 already covers repairs on archived cards. DRAFT for a comment there, NOT posted. From the janitor project board, 2026-10-10. Four rules still raise an error on archived cards that nothing may edit, namely MANDATE-FORGED, DANGLING-REF, ORDER-NPT-VIOLATED and BODY-STATE-CLAIM, on 5 cards here. Please lower them to a warning in the archived zone as G8 did for the checklist rules, or name the repair an archived card may receive. Also BODY-STATE-CLAIM fires on a sentence that describes past transitions. OWNER ITEM. Post or drop that draft. And, for information, two archived cards carry a mandate the main agent wrote on a user-floor card.
