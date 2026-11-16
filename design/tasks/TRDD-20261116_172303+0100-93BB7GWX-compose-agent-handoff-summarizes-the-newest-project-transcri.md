---
trdd-id: 93BB7GWX
title: compose_agent_handoff summarizes the newest project transcript, not its own session
column: todo
status: tasked
created: 2026-11-16T17:23:03+0100
updated: 2026-11-16T17:23:03+0100
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
approval-datetime: 2026-11-16T17:23:03+0100
---

# compose_agent_handoff summarizes the newest project transcript, not its own session

scripts/compose_agent_handoff.py (near line 72) picks the newest transcript of the project, so with two sessions in one project the summary can describe the other session. Found during TRDD-W6DZPXLG box 2, not re-verified. Related TRDD-P2ZN1AC8 items 4 and 5.

## Approval log

- 2026-11-16T17:23:03+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
