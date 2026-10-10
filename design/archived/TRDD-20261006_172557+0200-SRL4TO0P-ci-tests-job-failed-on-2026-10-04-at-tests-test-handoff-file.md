---
trdd-id: SRL4TO0P
title: CI Tests job failed on 2026-10-04 at tests/test_handoff_files.py line 166
column: complete
status: archived
created: 2026-10-06T17:25:57+0200
updated: 2026-10-10T21:45:54+0200
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
- 2026-10-10T21:45:54+0200 — COMPLETE by main-agent@ai-maestro-janitor. fixed by 37d72fcd9 on 2026-10-04; 16 CI runs since without recurrence in this file.


## STATE

2026-10-06: the failure did NOT recur in the v3.7.1 CI run (its two failures were other, Linux-only tests, fixed in 2d3b3aec). Check whether it recurs in v3.7.2 CI before investigating.
2026-10-10 21:45 CLOSED ON EVIDENCE. The assertion that failed on CI ('the touch is what this test is about', now tests/test_handoff_files.py line 172) belongs to test_a_dedupe_touch_does_not_reorder_other_keys. Commit 37d72fcd9 of 2026-10-04 (git blame of lines 166-170) pinned the second file's mtime 600 s into the past, with its reason in a comment: on Linux the coarse kernel clock gave the touch and the just-finished write the same mtime, so a strict greater-than was flaky. The fix therefore landed the day of the failure, before this card was written. CI since then (gh run list, workflow CI): 16 release runs from 3.7.1 to 3.8.11; three failed, none in this file: 3.7.1 (two Linux-only tests, fixed in 2d3b3aec, per the line above), 3.8.5 (tests/test_publish_stale_tag_recovery.py, a missing CHANGELOG.md in the temp tree), 3.8.8 (tests/test_memgrep_binary_stale.py::test_real_404_has_its_own_reason); the runs after each are green. NOT DONE: no run was made on a Linux host to reproduce the original failure; the proof is 16 CI runs without recurrence.

## Acceptance

- [x] The cause of the CI-only failure is named and fixed (coarse Linux clock, mtime pinned in 37d72fcd9, 2026-10-04).
- [x] It did not recur on CI (16 runs of the CI workflow from 3.7.1 to 3.8.11; the three failures were in other test files).
