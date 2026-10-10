---
trdd-id: WJVXIQRL
title: The burn verdict says a wall is projected from a burn slope when the trigger is a learned cap
column: blocked
status: tasked
created: 2026-10-05T22:11:16+0200
updated: 2026-10-10T16:31:38+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:16+0200
blocked-by: [AWIWXJIG]
pre-block-column: todo
---

# The burn verdict says a wall is projected from a burn slope when the trigger is a learned cap

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

live_burn_verdict returns 'wall projected in ~0 min (recent burn slope)' whenever the last reading is at or above the cap, although no slope was computed. Dormant while caps are off; false as soon as they return.

## Approval log

- 2026-10-05T22:11:16+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Findings

2026-10-10 16:31. READ by the main session, no code. Confirmed in live_burn_verdict (scripts/oauth_rotator/burn_gate.py): when projected_near is true the reason always says 'wall projected in ~N min (recent burn slope)', and with a learned cap a reading at or above the cap gives 0 minutes with no slope computed. It cannot be reached today: the cap list is always empty because cmd_auto discards learned_caps each tick, and with no cap a reading at or above 100 percent has already tripped the threshold check that runs before this function. The wording is to be fixed in the change that switches cap learning back on, which is TRDD-AWIWXJIG (its precondition (e) names this card). BLOCKED on TRDD-AWIWXJIG. Field case: none possible while the path is dormant.
