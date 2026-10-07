---
trdd-id: OEGPT048
title: The daemon keepalive error log is never rotated or capped
column: todo
status: tasked
created: 2026-10-07T04:44:45+0200
updated: 2026-10-07T04:44:56+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T04:44:45+0200
---

# The daemon keepalive error log is never rotated or capped

## Problem
The LaunchAgent sends the daemon's own stderr to daemon-keepalive.err.log in the janitor log dir (scripts/keepalive_install.sh, the StandardErrorPath line). Only files written through log_line are rotated (state.rotate_log_if_big), so this file grows without bound.

## Found while
Checking that the new 'assuming Claude is running' line of the rotator's running check also prints in the daemon process on the alert path, about once per stalled beat (10 in about 52 hours measured).

## Acceptance
- [ ] The file is rotated or capped like the other daemon logs, with a test.

## Approval log

- 2026-10-07T04:44:45+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

2026-10-07: not started. NEXT ACTION: add rotation or a cap for daemon-keepalive.err.log, test first.
