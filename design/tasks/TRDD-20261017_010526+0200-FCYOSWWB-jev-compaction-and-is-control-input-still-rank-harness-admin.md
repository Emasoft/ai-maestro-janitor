---
trdd-id: FCYOSWWB
title: Jev compaction and is_control_input still rank harness-admin commands as owner items
column: todo
status: tasked
created: 2026-10-17T01:05:26+0200
updated: 2026-10-17T01:05:26+0200
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
approval-datetime: 2026-10-17T01:05:26+0200
---

# Jev compaction and is_control_input still rank harness-admin commands as owner items

Split from TRDD-2UV4BBHP (b271c935). transcript_roles.is_control_input, used by external_clear.py:580,598 and jev_compaction.py:614, does not use is_non_instruction_command, so an owner-typed /login, /model or /plugin enable ... is still ranked as an owner item in the Jev-compacted copy and the external-clear digest, with the same slot-displacement effect fixed in session_continuity. To do: decide whether is_control_input should also return True for is_non_instruction_command (its control-word branch for resume/continue must stay), measure on real compacted copies, test.

## Approval log

- 2026-10-17T01:05:26+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
