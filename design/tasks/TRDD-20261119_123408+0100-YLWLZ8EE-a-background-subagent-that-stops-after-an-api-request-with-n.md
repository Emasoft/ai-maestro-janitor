---
trdd-id: YLWLZ8EE
title: A background subagent that stops after an API request with no reply is only reported as a LOW stalled finding and never woken or restarted
column: todo
status: tasked
created: 2026-11-19T12:34:08+0100
updated: 2026-11-19T12:34:15+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-19T12:34:08+0100
relevant-rules: [34]
---

# A background subagent that stops after an API request with no reply is only reported as a LOW stalled finding and never woken or restarted

## Symptom (by the orchestrator, 2026-11-19, unverified unless stated)

- Two background subagents (a secret-shield expert and an env-tools worker) sat 2.5 hours with no reply after an API request at 21:16-21:17 on 2026-11-18. Their transcripts end with an api-request row and no assistant reply, until they were stopped at 23:45.
- The janitor surfaced only a LOW WORKER-STALLED finding ("silent 8882s"). It did not wake, resume or restart them.

## Governing

PRRD G34.1 (an issue must be solved, not just reported).

## Done means

- [ ] Reproduced or shown absent, fixed with a test where one fits.

## Approval log

- 2026-11-19T12:34:08+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
