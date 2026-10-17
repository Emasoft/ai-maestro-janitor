---
trdd-id: XRT9LOQL
title: The git listing that replaced the detector tree walks has untested branches
column: complete
status: archived
created: 2026-10-10T20:03:43+0200
updated: 2026-10-17T04:53:01+0200
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
- 2026-10-17T04:53:01+0200 — COMPLETE by main-agent@ai-maestro-janitor. archived → complete.

## STATE

2026-10-16: tests for items 1-4 added; committed in 57b3e5c0 (9 pass).
2026-10-17: CORRECTION. The tests are COMMITTED in 57b3e5c0 (tests/test_git_listing_branches.py, 9 pass), not uncommitted. The timeout-branch test uses a patched run_git_readonly seam; the only alternative is a real 30 s wait.
Open: the timeout-fallback decision. A measurement worker is running on the external volume (scripts_dev/xrt9-measure/), with a folder/* run and the walk-to-listing ratio per N; its report lands in docs_dev/*-XRT9LOQL-measure.md. Before closing, read tests/test_git_listing_branches.py lines 106-210 against items 2-4. End column: complete if no code change, testing if the decision is skip-with-log. Keep the note that 0d42c65f's claim (git never enters an ignored dir) is false for folder/* rules and must stay out of release notes.
DECISION 2026-10-17, measured on the external volume (APFS) with an untracked, not-ignored folder of tiny files, about 1000 per dir: git ls-files cold/warm took 0.11/0.11 s at 50k, 0.35/0.37 s at 200k, and 3.51/1.67 s at 500k. The detectors fallback walk (_tree_paths: sorted rglob plus drop_gitignored) took 1.11, 3.49 and 15.58 s, which is 4 to 10 times slower than the listing. Reaching 30 s would take roughly 4 to 17 million files (extrapolated), so a field timeout more likely comes from a slow or contended volume than from file count. Choice: KEEP the fallback walk. Skip-with-log would be blind on 100% of listing timeouts; the fallback is blind only when the walk also overruns the 120 s detector kill (scripts/dispatch.py:1301), and it can still succeed when the timeout was transient. A layout of big/* plus a negation listed in 0.01 s, so git did not descend there. Possible later improvement: bound the fallback by the remaining budget and raise a finding if it aborts. No code change.

## Acceptance

- [x] (1) git_utils.own_files timeout and missing-git branches tested (57b3e5c0)
- [x] (2) non-entry proven for _tree_paths, _has_test_files, _find_named (57b3e5c0)
- [x] (3) tracked file deleted from disk tolerated by each detector (57b3e5c0)
- [x] (4) _has_test_files plain-folder fallback gives the pre-rewrite answer (57b3e5c0)
- [x] Measured timeout-fallback decision: keep the fallback walk (see DECISION 2026-10-17 in STATE)
