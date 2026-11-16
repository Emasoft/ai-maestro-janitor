---
trdd-id: A8I95PPV
title: ticket-dispatch formats its git failure line itself instead of git_root_error_reason
column: todo
status: tasked
created: 2026-11-16T17:23:16+0100
updated: 2026-11-16T17:23:16+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
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

# ticket-dispatch formats its git failure line itself instead of git_root_error_reason

scripts/detectors/ticket-dispatch.py lines 180-187 build their own GitRootError line; reuse trdd_common.git_root_error_reason so paths are scrubbed the same way (TRDD-7KPG2PCO).

## Approval log

- 2026-11-16T17:23:16+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
