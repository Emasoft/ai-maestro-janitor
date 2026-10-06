---
trdd-id: SRL4TO0P
title: CI Tests job failed on 2026-10-04 at tests/test_handoff_files.py line 166
column: todo
status: tasked
created: 2026-10-06T17:25:57+0200
updated: 2026-10-06T17:51:50+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T17:25:57+0200
---

# CI Tests job failed on 2026-10-04 at tests/test_handoff_files.py line 166 and nobody looked

The GitHub CI run for the 3.7.0 release on 2026-10-04 failed in the Tests job: tests/test_handoff_files.py:166 AssertionError "the touch is what this test is about" (the same suite passes locally: 17976 passed on 2026-10-06). Find why it fails only on CI (filesystem mtime resolution, runner clock, ordering), fix the test or the code, and confirm on the next CI run. Check the CI result of v3.7.1 first: it may have recurred.

## Approval log

- 2026-10-06T17:25:57+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.


## STATE

2026-10-06: the failure did NOT recur in the v3.7.1 CI run (its two failures were other, Linux-only tests, fixed in 2d3b3aec). Check whether it recurs in v3.7.2 CI before investigating.
