---
trdd-id: 3OCFOXD2
title: The main session printed two long transcript dumps into its own context
column: todo
status: tasked
created: 2026-10-05T22:11:21+0200
updated: 2026-10-05T22:11:21+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:21+0200
---

# The main session printed two long transcript dumps into its own context

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Two searches on 2026-10-05 printed about 120 and about 80 long rows and the token-spike hook fired. Such searches belong in a worker or must write to a file and print a count.

## Approval log

- 2026-10-05T22:11:21+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
