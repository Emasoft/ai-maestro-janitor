---
trdd-id: X0EBVDVN
title: The heartbeat prints the memory lint count on fires that are otherwise quiet
column: todo
status: tasked
created: 2026-10-05T22:08:51+0200
updated: 2026-10-05T22:08:51+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:51+0200
---

# The heartbeat prints the memory lint count on fires that are otherwise quiet

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed about once an hour: a fire whose only other line was the quiet token also printed 'memgrep lint: 150 finding(s), none at or above ERROR'. The heartbeat contract says a fire adds to its one line only when something needs the human. To do: decide whether a lint total with no error belongs in the conversation or only in the findings ledger.

## Approval log

- 2026-10-05T22:08:51+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
