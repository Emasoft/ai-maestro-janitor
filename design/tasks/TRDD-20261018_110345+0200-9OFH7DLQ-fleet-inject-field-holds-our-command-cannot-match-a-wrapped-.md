---
trdd-id: 9OFH7DLQ
title: fleet_inject field_holds_our_command cannot match a wrapped command
column: backburner
status: tasked
created: 2026-10-18T11:03:45+0200
updated: 2026-10-18T11:03:45+0200
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
approval-datetime: 2026-10-18T11:03:45+0200
---

# fleet_inject field_holds_our_command cannot match a wrapped command

Found by the measure pass for TRDD-85NZX5RJ (2026-10-18), by reading the code, not by running it on a wrapped capture. scripts/lib/fleet_inject.py:474 field_holds_our_command does its own .strip() and a vocabulary membership test on extract_prompt_field's result, not prompt_field_shows_only, so a command that wraps past one row of the input box reads back with the two-space continuation indent at each wrap and never matches. Not yet shown to bite: fleet commands may all fit one row. TO DO FIRST: list the fleet vocabulary and the longest command; if any can wrap at a realistic pane width, reuse terminal_trigger._norm_wrap_spaces (8dae3e5e) with a real-capture test.

## Approval log

- 2026-10-18T11:03:45+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
