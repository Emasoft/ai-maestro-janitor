---
trdd-id: LSGY6PKA
title: One rate limit records a usage cap for both windows with no attribution
column: todo
status: tasked
created: 2026-10-05T22:11:15+0200
updated: 2026-10-05T22:11:15+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:15+0200
---

# One rate limit records a usage cap for both windows with no attribution

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

observe_wall writes the freshest reading of the 5h and of the 7d window from a single 429. Cap learning is off since TRDD-YVC3F06V; this is the defect to remove before it is switched on again.

## Approval log

- 2026-10-05T22:11:15+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
