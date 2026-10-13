---
trdd-id: 7J3QPSPD
title: A failed write of the rate-limit recovery marker is silent so the daemon never retries and nothing records it
column: complete
status: tasked
created: 2026-10-10T16:33:52+0200
updated: 2026-10-13T13:17:57+0200
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
approval-datetime: 2026-10-10T16:33:52+0200
implementation-commits: [eac434749c1d5e09db58a1108423a353e67ddc25]
release-via: publish
---

# A failed write of the rate-limit recovery marker is silent so the daemon never retries and nothing records it

Found on 2026-10-10 while verifying TRDD-GTXZADFY; read from the code, not observed. In scripts/hooks/on-stop-failure.py the write of recovery-requested.ts sits inside contextlib.suppress(Exception). If it fails (disk full, permissions, a missing directory) the detached first launch still starts, but the daemon has no marker to service, so there is no second run, and no log line says the marker was not written. To do: log the failure through state.log_line in the same place (the hook must still never raise), with one test that makes the write fail and asserts the log line. Smallest change; no retry logic is to be added.

## Approval log

- 2026-10-10T16:33:52+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-12T02:02:13+0200 — column → testing. Existing logging fix has fresh passing affected suites and all three checkers; review found no blocker; final acceptance and release gates not claimed
- 2026-10-12T18:12:28+0200 — column → ai_review. Scoped implementation acceptance verified; review accepted logging and preserved launch attempt
- 2026-10-13T13:17:57+0200 — column → complete. Original scoped logging requirement and named regression test verified; committed implementation awaits publication; live recovery and packaged pipeline success not claimed

## Verification

2026-10-11T13:28:34+0200 — Existing uncommitted fix verified by the main session: marker-write exceptions log through state.log_line; logging failure is isolated so the initial detached launch still proceeds. Pinning test test_unwritable_recovery_marker_is_logged_and_the_first_launch_still_fires uses a real directory collision to fail os.replace and intercepts Popen to avoid credential rotation. Focused suites: 243 passed. Whole-tree ruff passed, mypy found no issues in 536 source files, pyright reported zero errors/warnings. Full pytest: 18386 passed, 2 skipped, 8 subtests passed, exit 0. CPV v5.16.2 strict invocation without exemption exited 2 at its own integrity-manifest mismatch before plugin validation. No release, commit, live rotation or closure performed. FIELD CASE UNOBSERVED; strict verdict remains blocked.
2026-10-12 — Fresh live-checkout verification: 243 tests passed in 35.14s across test_on_stop_failure_active_recovery.py and test_dispatch_phases.py; earlier this session Ruff, mypy and Pyright each exited 0. Captured-diff adversarial review found no blocking defect. state.py log_line inspected: filesystem initialization, rotation and append; no retry loop in this function. Logging failure is suppressed to preserve the initial launch attempt, but simultaneous marker/log failure remains untested. Test intercepts Popen and proves an attempt, not child execution. No new full-suite or strict CPV result, no release or commit.
2026-10-12 — Implementation acceptance met by source inspection and this session checks: real marker-write failure logs through state.log_line; nested log-error suppression preserves the initial launch attempt; no retry logic added. Focused suites 243 passed; full suite 18386 passed, 2 skipped; Ruff, mypy and Pyright exited 0. Review accepted the scoped requirement. Popen interception proves an attempt, not child execution. Simultaneous marker/log failure and live recovery remain untested; strict CPV and publication remain separate and unverified. Implementation remains uncommitted.
2026-10-13 — Implementation committed in eac434749c1d5e09db58a1108423a353e67ddc25, superseding earlier uncommitted notes. Main-session pinning test passed; fresh Ruff, mypy (536 source files), and Pyright passed; full pytest 18386 passed, 2 skipped in 1177.16s. Complete pinned CPV v5.16.2 source strict validation exited 0 with zero blocking findings and 42 warnings, without integrity exemption. The packaged uvx publishing route still fails CPV internal integrity verification; source validation does not repair that route. FIELD CASE UNOBSERVED; intercepted Popen proves an initial launch attempt, not successful child execution; simultaneous marker/log failure remains untested.

## Acceptance

- [x] Marker-write failure logs through state.log_line; the hook remains non-raising and preserves the initial launch attempt; the marker-failure regression test passes; no retry logic added.
