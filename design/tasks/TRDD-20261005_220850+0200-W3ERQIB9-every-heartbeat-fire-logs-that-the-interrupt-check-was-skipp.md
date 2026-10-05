---
trdd-id: W3ERQIB9
title: Every heartbeat fire logs that the interrupt check was skipped because the session is unknown
column: todo
status: tasked
created: 2026-10-05T22:08:50+0200
updated: 2026-10-05T22:08:50+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:50+0200
---

# Every heartbeat fire logs that the interrupt check was skipped because the session is unknown

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed in the dispatch log of two other projects on every fire read: 'heartbeat: interrupt check skipped, session unknown'. To do: find what the check needs to know the session, why it is unknown on an ordinary fire, and what protection is lost when it is skipped.

## Approval log

- 2026-10-05T22:08:50+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
