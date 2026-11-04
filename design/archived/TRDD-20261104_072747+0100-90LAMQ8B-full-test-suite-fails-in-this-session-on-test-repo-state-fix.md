---
trdd-id: 90LAMQ8B
title: full test suite fails in this session on test_repo_state fixtures and idle-clear tests
column: complete
status: archived
created: 2026-11-04T07:27:47+0100
updated: 2026-11-04T19:42:02+0100
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
approval-datetime: 2026-11-04T07:27:47+0100
implementation-commits: [52c8f975, fd654580]
---

# full test suite fails in this session on test_repo_state fixtures and idle-clear tests

## Symptom
In this session the full suite gives 5 failed and 31 errors, the same counts at f3a2313d and at 5480fc77, all outside memory_txn: tests/test_repo_state.py (31 errors in fixtures) and tests/test_dispatch_phases.py::test_idle_clear_* (5 failures, _phase_idle_clear_nudge returns False; one assertion says "no readable channel: the attempt itself should still be made").
## Measured cause, test_repo_state
`git -C <bare>.git symbolic-ref HEAD refs/heads/main` exits 128 with "cannot use bare repository ... (safe.bareRepository is 'explicit')". `git config --show-origin safe.bareRepository` reports origin "command line", so the setting arrives through the session's environment (GIT_CONFIG_PARAMETERS or GIT_CONFIG_COUNT), not through a gitconfig file. The fixtures depend on the host's git configuration.
## Not yet measured
The cause of the 5 idle-clear failures, and whether CI sees either set. Measured 2026-11-04: bd6a7eca, the commit before TRDD-C88OZANX, gives the same 5 failed and 31 errors.
2026-11-04: both measured, see the Approval log lines of 2026-11-04T19:39 and later.
## Done when
- [x] the test_repo_state fixtures pass with safe.bareRepository=explicit set (for example by addressing bare repos with --git-dir, or by isolating git configuration in the fixture), with a test that sets it on purpose
- [x] the idle-clear failures are root-caused and fixed
- [x] the full suite passes in a session that has the same environment

## Approval log

- 2026-11-04T07:27:47+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-04T19:39+0100 — EVIDENCE that would have gone in the STATE block (the STATE block was not written: no trddgrep verb inserts after the title, and edit does not show newline support): fd654580 (notice in the end-of-run summary): with an option set the line appears once and names it, with every option unset it appears 0 times; tests/test_repo_state.py plus test_dispatch_phases.py -k 'idle_clear or repo' 60 passed; ruff, mypy and pyright clean.
- 2026-11-04T19:42:02+0100 — COMPLETE by main-agent@ai-maestro-janitor. all three Done-when items met: full suite 18932 passed, 0 failed, 0 errors in this session before the review follow-ups; after them the changed test files and the linters passed; fixed in 52c8f975 and fd654580, reviewed.
