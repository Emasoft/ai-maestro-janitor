---
trdd-id: 5CCRBM1H
title: The new stuck alert text exists inline in code and again as a literal in a test
column: todo
status: tasked
created: 2026-10-05T22:11:22+0200
updated: 2026-10-05T22:11:22+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:22+0200
---

# The new stuck alert text exists inline in code and again as a literal in a test

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Commit 5bdb9521 put the text inline because fastedit could not add a module constant. Give it one name.

## Approval log

- 2026-10-05T22:11:22+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
