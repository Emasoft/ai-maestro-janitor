---
trdd-id: FSNVU81M
title: rotator _log_swallowed has no test that forces either swallowed error
column: complete
status: archived
created: 2026-11-19T23:14:14+0100
updated: 2026-11-19T23:26:25+0100
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
- 2026-11-19 main-agent: tests committed in fe16ed55; 207 passed against the committed rotator.py (hash checked equal to HEAD before and after the run); mutation runs on scratch copies show each guard is load-bearing (report reports_dev/sonnet-worker/20261119_231844+0100-fsnvu81m.md).
- 2026-11-19T23:26:25+0100 — COMPLETE by main-agent@ai-maestro-janitor. tests committed in fe16ed55, 207 passed, mutation-checked.

## Acceptance

- [x] A failing record_rotation_success logs the exception type name only (fe16ed55)
- [x] A non-OSError from _log inside _log_swallowed does not escape (fe16ed55)
- [x] A broken stderr does not escape and the fallback write is attempted (fe16ed55)
