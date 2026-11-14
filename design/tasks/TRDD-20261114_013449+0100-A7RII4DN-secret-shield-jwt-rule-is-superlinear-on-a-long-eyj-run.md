---
trdd-id: A7RII4DN
title: Secret shield jwt rule is superlinear on a long eyJ run
column: todo
status: tasked
created: 2026-11-14T01:34:49+0100
updated: 2026-11-14T01:34:53+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-14T01:34:49+0100
---

# Secret shield jwt rule is superlinear on a long eyJ run

## Approval log

- 2026-11-14T01:34:49+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Why

Worker probe 2026-11-14 (report path above, out/quad.log): 64 KB of eyJ- repeated takes about 600 ms with the current jwt rule (rules/key-material.ts:15) and about 604 ms with the widened candidate; 16 KB takes 40 ms, so the cost grows about 15x for 4x input. Extrapolated, not measured: about 9 s at 256 KB, near the assumed 10 s hook limit (TRDD-U5O72MGA). Same class as U5O72MGA.

## Done when

The jwt rule's time on 256 KB and 1 MB of the repeated run is measured; if it can exceed the hook limit, the rule is bounded (fail closed, test) or the case is recorded with a bound.
