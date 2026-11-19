---
trdd-id: FSNVU81M
title: rotator _log_swallowed has no test that forces either swallowed error
column: todo
status: tasked
created: 2026-11-19T23:14:14+0100
updated: 2026-11-19T23:14:14+0100
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
approval-datetime: 2026-11-19T23:14:14+0100
---

# rotator _log_swallowed has no test that forces either swallowed error

The two rotator.py sites changed for B110 (record_rotation_success failure and the tick-step catch) now log the exception type through _log_swallowed. No test triggers either path. Add tests in tests/test_oauth_rotator.py: make gs.record_rotation_success raise and assert the log line names only the type; make _log raise a non-OSError and assert nothing escapes. Found 2026-11-19 by the harness review of the rotator worker. Parent TRDD-SWQXCIOS.

## Approval log

- 2026-11-19T23:14:14+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
