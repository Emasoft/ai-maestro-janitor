---
trdd-id: 6O2M9V1K
title: The review gate asks for a new review after every card-only commit and its reviewers cannot see commits of the same turn
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

# The review gate asks for a new review after every card-only commit and its reviewers cannot see commits of the same turn

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed about eight times in one session: after a commit that changed only cards, the stop gate demanded another adversarial review; fixing what that review found needed another commit, which re-armed the gate. Four reviews also reported that a commit 'does not exist' because a fork inherits the transcript only up to the turn that spawns it. The gate belongs to another project. To do: write up the two behaviours with examples and send them to that project's owner through the usual channel; no change is made to its code from here.

## Approval log

- 2026-10-05T22:08:51+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
