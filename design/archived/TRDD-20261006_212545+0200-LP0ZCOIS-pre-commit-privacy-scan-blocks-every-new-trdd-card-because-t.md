---
trdd-id: LP0ZCOIS
title: Pre-commit privacy scan blocks every new TRDD card because the author token looks like an ssh user and host
column: complete
status: archived
created: 2026-10-06T21:25:45+0200
updated: 2026-10-10T21:51:41+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:45+0200
---

# Pre-commit privacy scan blocks every new TRDD card because the author token looks like an ssh user and host

Source: GitHub issue Emasoft/ai-maestro-janitor#314 (opened 2026-09-28). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The pre-commit privacy scan flags the required author token of a new card as a private-path ssh-user-host leak, so every newly minted card is refused at commit. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:45+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T21:51:41+0200 — COMPLETE by main-agent@ai-maestro-janitor. already fixed and shipped; issue 314 closed with commit and release.

## Findings

2026-10-10 21:51 CLOSED ON EVIDENCE, no new code. Commits 8792ca19 and bbe20017 of 2026-09-28, first in v3.7.0: the pre-commit privacy scan no longer reads a card's author token (main-agent at project-id) as an ssh target. Test test_trdd_governance_author_token_does_not_block (tests/test_staged_privacy_scan.py line 204) and two siblings named in the issue. Issue 314 is CLOSED as completed on 2026-10-06 and its last comment names the commits and the release. Checked by this session: the commits exist with those subjects and the first v-tag containing them is the one named; the named tests exist by name in the tree. NOT DONE: the tests were not run on their own today.

## Acceptance

- [x] The symptom is gone in a test that failed before the fix (tests and commits in Findings).
- [x] A closing comment on the issue names the commit and the release (issue 314).
