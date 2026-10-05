---
trdd-id: PYV26AYU
title: The host reaches load averages in the hundreds from the agent fleet itself
column: todo
status: tasked
created: 2026-10-05T22:11:19+0200
updated: 2026-10-05T22:13:35+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:19+0200
---

# The host reaches load averages in the hundreds from the agent fleet itself

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Load average 232 on 2026-10-05 and 335 to 403 on 2026-10-02. Find the main contributors (heartbeat fires of every session, workers, local models) and what the janitor can throttle.

## Approval log

- 2026-10-05T22:11:19+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Corrections

2026-10-05 (review): the title states a cause; only the load figures were measured. Read it as the hypothesis.
