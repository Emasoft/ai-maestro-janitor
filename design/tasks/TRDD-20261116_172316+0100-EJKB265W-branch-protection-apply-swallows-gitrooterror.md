---
trdd-id: EJKB265W
title: branch_protection_apply swallows GitRootError
column: todo
status: tasked
created: 2026-11-16T17:23:16+0100
updated: 2026-11-16T17:23:16+0100
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
approval-datetime: 2026-11-16T17:23:16+0100
---

# branch_protection_apply swallows GitRootError

scripts/guard/branch_protection_apply.py lines 198-204 catch the git root failure without saying so. Found during TRDD-7KPG2PCO research, not re-verified.

## Approval log

- 2026-11-16T17:23:16+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
