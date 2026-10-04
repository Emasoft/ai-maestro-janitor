---
trdd-id: DGBZVZPP
title: memgrep tests share process-wide state and fail at random under load
column: ai_review
status: tasked
created: 2026-10-04T14:01:11+0200
updated: 2026-10-04T14:01:11+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-04T14:01:11+0200
---

# memgrep tests share process-wide state and fail at random under load

## Symptom

Rust tests of the bundled search tool failed once under machine load and passed on rerun, four different tests on 2026-10-04; the push gate runs this suite, so a release can be refused at random.

## Cause 1 (REPRODUCED)

The jev mock servers did one read and closed with unread request bytes, so the client could get a connection reset in place of the scripted reply. Fix: drain the whole request before replying. 60 of 60 runs clean at 32 threads after the fix.

## Cause 2 (INFERRED from reading the code, not reproduced)

Subprocess tests in tests/cli.rs all used the real global-state folder and queued on one shared lock with a 10 second timeout. Fix: each test thread gives its children a private state folder.

## Cause 3 (INFERRED from reading the code, not reproduced)

About 110 test sites set process-wide environment variables while tests run in parallel; five separate module mutexes serialized nothing across modules and readers took none. Fix: new module src/scoped_env.rs, a per-thread override in test builds, exactly std::env::var in release builds; six variable names, each with one production reader routed through it.

## Verification 2026-10-04

Clippy clean; 409 and 196 tests pass in parallel, serially, and in two repeat runs; release build has no warnings; with the override lookup disabled 16 unit tests fail, so the overrides are load-bearing; no assertion removed.

## Open items

- OPEN: eight unit tests set no override and still reach the real global-state folder in a normal run (three mem_reference tests, two memory tests, three xi9_cli tests; names in reports_dev/20261004_140007+0200-memgrep-isolation-verify.md section C).
- OPEN: nothing stops a new test from calling the process-wide setter again; add a clippy disallowed-methods entry for std::env::set_var and remove_var.
- OPEN: the jev tests still set process environment variables under their own lock (two helper sites); cache_hit_skips_network failure was assumed to share cause 1, not proven.
- OPEN: a test run with overrides ignored writes fixture pages into the real USER memory folder, which shows the tests can reach real state whenever an override is missed.

## Approval log

- 2026-10-04T14:01:11+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
