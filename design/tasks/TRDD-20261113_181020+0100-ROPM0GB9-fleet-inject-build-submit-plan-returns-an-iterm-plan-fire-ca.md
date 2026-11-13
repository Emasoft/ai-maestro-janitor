---
trdd-id: ROPM0GB9
title: fleet_inject build_submit_plan returns an iTerm plan fire cannot run
column: todo
status: tasked
created: 2026-11-13T18:10:20+0100
updated: 2026-11-13T18:10:20+0100
current-owner: user
created-by: user
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: user
mandate: true
mandated-by: none
approved: true
approval-judge: user
approval-datetime: 2026-11-13T18:10:20+0100
---

# fleet_inject build_submit_plan returns an iTerm plan fire cannot run

Found by the TRDD-RJJGXPIK recovery worker (reports_dev/sonnet-worker/20261113_174446+0100-rjjgxpik-c23.md, finding 2). In scripts/lib/fleet_inject.py, build_submit_plan returns an iTerm plan carrying only `steps`, but fire() reads plan['osascript'] for the iTerm channel, which raises KeyError. That is the Enter-alone step pane_actuate.build_step_plan uses after a queue flush. Every iTerm recovery rung that needs a separate Enter therefore crashes instead of submitting. Fix: give the iTerm submit plan its osascript, the way the new _readback_split_plan helper does, and add a test that fire() accepts an iTerm submit plan. Verify that the bug reproduces before fixing it.

## Approval log

- 2026-11-13T18:10:20+0100 — MANDATE issued by user (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
