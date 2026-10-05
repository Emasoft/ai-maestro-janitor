---
trdd-id: POOBOHDM
title: A burn projection with no target falls through to exhausted and stuck
column: todo
status: tasked
created: 2026-10-05T22:11:17+0200
updated: 2026-10-05T22:11:17+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:17+0200
---

# A burn projection with no target falls through to exhausted and stuck

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

The stay-put branch for a projection covers only the case where every target is spent on the model in use. With no target at all the tick logs 'exhausted' and writes the stuck marker for what is only a projection. Read from the code; a first fix was dropped in review because it would also silence a real learned cap.

## Approval log

- 2026-10-05T22:11:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
