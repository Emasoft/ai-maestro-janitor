---
trdd-id: AHKL0L4H
title: A blocked card whose blocker was archived never reads as ready and no column fits a parent waiting on prerequisites
column: backburner
status: tasked
created: 2026-10-05T01:53:42+0200
updated: 2026-10-05T01:53:42+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T01:53:42+0200
---

# A blocked card whose blocker was archived never reads as ready and no column fits a parent waiting on prerequisites

Found 2026-10-05. Two tooling gaps in the card tool (trddgrep), which may live in the ai-maestro repository; ownership not checked. (1) Measured on two scratch cards: card B blocked on card A; after A was completed and archived, trddgrep why B printed BLOCKED with no locally-resolvable blocker and never READY, and B stayed in blocked with blocked-by unchanged. So a probe of the form blocker-probe [trddgrep, why, <id>] with blocker-holds-if not-match:READY never clears in that case. Not tested: a blocker that is terminal but not archived, and a card blocked through npt. Cards carrying that probe form include 3HLI7DMK, JSQSJ3PZ and K9AHY1ZB. Completing six cards on 2026-10-05 also left them as stale entries in another card blocked-by list (GRAPH-DANGLING-BLOCKER rose from 6 to 12 until the list was trimmed by hand, commit e3cb3be6): the tool does not clear a closed blocker from the lists that name it. (2) No column truthfully states a parent card waiting on prerequisite cards that sit in testing: testing raises ORDER-NPT-VIOLATED, blocked has the probe problem, dev claims work in flight. JSQSJ3PZ and K9AHY1ZB sit in dev for that reason (commit fd403e0c). First step: find which repository owns trddgrep, then file it there or fix it here.

## Approval log

- 2026-10-05T01:53:42+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
