---
trdd-id: LAUPB305
title: secret-shield test gate intermittently cannot parse the pass and fail counts after claude exits 0
column: backburner
status: tasked
created: 2026-11-14T08:03:10+0100
updated: 2026-11-14T08:03:10+0100
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
approval-datetime: 2026-11-14T08:03:10+0100
---

# secret-shield test gate intermittently cannot parse the pass and fail counts after claude exits 0

## Symptom
On 2026-11-14 a worker run of scripts/run_secret_shield_tests.py failed with: could not parse the pass/fail counts from the run's output. The claude plugin test output it printed stopped at line 525, with no summary lines, and claude exited 0. A re-run minutes later at load 15.5 passed (841 pass, 0 fail). Not reproduced since.

## Evidence
reports_dev/cheap-worker/20261114_080021+0100-probe-escaped-revert.md (the failing run and its output). The parse check is scripts/run_secret_shield_tests.py main(), the branch that returns the could-not-parse failure after code == 0.

## Why it matters
The gate runs inside scripts/publish.py. An intermittent false failure blocks a release; a fix that loosens the parse to make it pass would let an incomplete run ship. Fail closed stays.

## Work
1. Reproducer: run the gate N times (N >= 30) under idle and under load, record each exit, output byte length and last line.
2. On the parse-failure path, print the output byte length, line count and last 20 lines before the full output, so the next occurrence is diagnosable from the log alone.
3. Find whether the output is cut by claude itself (exit before flush) or by the reader in _run_in_own_session; fix the cause, never the check.

## Done when
The cause is named with a reproducer, or N runs show no failure and step 2 is committed so a recurrence is diagnosable.

## Approval log

- 2026-11-14T08:03:10+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
