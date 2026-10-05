---
trdd-id: WJVXIQRL
title: The burn verdict says a wall is projected from a burn slope when the trigger is a learned cap
column: todo
status: tasked
created: 2026-10-05T22:11:16+0200
updated: 2026-10-05T22:11:16+0200
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
---

# The burn verdict says a wall is projected from a burn slope when the trigger is a learned cap

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

live_burn_verdict returns 'wall projected in ~0 min (recent burn slope)' whenever the last reading is at or above the cap, although no slope was computed. Dormant while caps are off; false as soon as they return.

## Approval log

- 2026-10-05T22:11:16+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
