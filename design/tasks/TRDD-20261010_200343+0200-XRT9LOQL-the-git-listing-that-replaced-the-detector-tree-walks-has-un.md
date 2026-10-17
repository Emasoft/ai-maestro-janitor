---
trdd-id: XRT9LOQL
title: The git listing that replaced the detector tree walks has untested branches
column: todo
status: tasked
created: 2026-10-10T20:03:43+0200
updated: 2026-10-17T04:41:42+0200
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
approval-datetime: 2026-10-10T20:03:43+0200
---

# The git listing that replaced the detector tree walks has untested branches

Goal: write the tests the review of 0d42c65f found missing for TRDD-WOI8GO1S. (1) git_utils.own_files: the timeout branch (log line, then None) and the missing-git branch (OSError, silent None). (2) Non-entry proven for the other three helpers, as tests/test_typosquat_watcher.py does for _lockfile_paths: repo-trust-score _tree_paths and _has_test_files, supply-chain-fingerprints _find_named. (3) A tracked file deleted from disk is tolerated by each detector. (4) The fallback of _has_test_files on a plain folder gives the same answer as before the rewrite. Also decide, with a measurement on a tree holding a large folder that is NOT ignored, whether the 30 s timeout falling back to the full walk should instead skip the fire with a log line. The commit message of 0d42c65f says git never enters an ignored directory; that is false for rules written folder/* and must stay out of release notes.

## Approval log

- 2026-10-10T20:03:43+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

2026-10-16: added tests/test_git_listing_branches.py (9 tests pass; items 1-4 covered; uncommitted, pending orchestrator commit). OPEN: the timeout-fallback measurement/decision (skip the fire vs full walk) is not done; card stays in todo.
2026-10-17: CORRECTION. The tests are COMMITTED in 57b3e5c0 (tests/test_git_listing_branches.py, 9 pass), not uncommitted. The timeout-branch test uses a patched run_git_readonly seam; the only alternative is a real 30 s wait.
Open: the timeout-fallback decision. A measurement worker is running on the external volume (scripts_dev/xrt9-measure/), with a folder/* run and the walk-to-listing ratio per N; its report lands in docs_dev/*-XRT9LOQL-measure.md. Before closing, read tests/test_git_listing_branches.py lines 106-210 against items 2-4. End column: complete if no code change, testing if the decision is skip-with-log. Keep the note that 0d42c65f's claim (git never enters an ignored dir) is false for folder/* rules and must stay out of release notes.
