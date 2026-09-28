---
trdd-id: DG2V7D5P
title: The janitor reports repo state, commits ahead or behind origin, and commits made outside publish.py
column: testing
created: 2026-09-24T08:11:52+0200
updated: 2026-09-28T13:04:20+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T08:11:52+0200
status: tasked
---

# The janitor reports repo state, commits ahead or behind origin, and commits made outside publish.py

no detector computes ahead/behind. main was 157 commits ahead of the last release on 2026-09-24 and nothing reported it. dirty-tree.py reads only `git status --porcelain`. branch-protection.py covers rulesets only. Report ahead/behind per branch, and flag a default-branch commit not made through publish.py.

## Approval log

- 2026-09-24T08:11:52+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-27T17:16:32+0200 — column → testing by user. detector + 14 tests landed and verified by main (commit 66450ec8); registration in dispatch.py is the remaining integration step, tracked on the card

## Implementation

2026-09-27: detector landed as scripts/detectors/repo-state.py + tests/test_repo_state.py (commit 66450ec8) via lean-worker, verified independently by the main agent (14 passed, ruff+mypy clean). Heuristic: commits newer than the newest strict-semver v* tag whose subject is not publish.py's bump subject; ahead/behind via @{upstream}; semver ordering not creatordate (same-second tiebreak bug found+fixed during testing); GIT_OPTIONAL_LOCKS=0 throughout (janitor#245). REMAINING: dispatch.py registration + ADVISORY classification (integration pass).

## Acceptance

- [x] repo-state detector reports ahead/behind per branch + non-publish default-branch commits: tests/test_repo_state.py 14 tests green (run 2026-09-28 exit 0; landed 66450ec8, main-verified: 14 passed, ruff+mypy clean)
- [x] detector runs with GIT_OPTIONAL_LOCKS=0 and semver (not creatordate) tag ordering: verified by source read recorded in Implementation (66450ec8; same-second tiebreak bug found+fixed during testing)
- [ ] dispatch.py registration + ADVISORY classification (integration pass): OPEN - remains on the card
