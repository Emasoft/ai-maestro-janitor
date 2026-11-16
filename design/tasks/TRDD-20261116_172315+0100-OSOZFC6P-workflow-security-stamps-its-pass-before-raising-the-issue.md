---
trdd-id: OSOZFC6P
title: workflow-security stamps its pass before raising the issue
column: todo
status: tasked
created: 2026-11-16T17:23:15+0100
updated: 2026-11-16T17:23:15+0100
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
approval-datetime: 2026-11-16T17:23:15+0100
---

# workflow-security stamps its pass before raising the issue

scripts/detectors/workflow-security.py near line 208 writes its stamp before the issue is raised, so a raise that fails (for example on a git failure, TRDD-7KPG2PCO) may not be retried on the next pass. Verify the ordering before fixing.

## Approval log

- 2026-11-16T17:23:15+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
