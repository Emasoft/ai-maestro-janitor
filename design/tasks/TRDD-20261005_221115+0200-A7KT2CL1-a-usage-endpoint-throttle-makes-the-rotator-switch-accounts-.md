---
trdd-id: A7KT2CL1
title: A usage-endpoint throttle makes the rotator switch accounts when a target exists
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

# A usage-endpoint throttle makes the rotator switch accounts when a target exists

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

On a debounced 429 from the usage endpoint the tick sets near to true and rotates onto a safe, a model-spent or an unmeasured alternate. TRDD-QHACQPPG covers only the case with no target. Read from the code and a review; not observed happening.

## Approval log

- 2026-10-05T22:11:15+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
