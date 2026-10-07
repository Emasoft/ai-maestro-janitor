---
trdd-id: EMMXG7GW
title: GHCFG-001 NO_PR_REVIEW false positive fires again on a solo-owned repo
column: complete
status: archived
created: 2026-10-06T21:26:04+0200
updated: 2026-10-07T07:50:36+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:26:04+0200
---

# GHCFG-001 NO_PR_REVIEW false positive fires again on a solo-owned repo

Source: GitHub issue Emasoft/ai-maestro-janitor#327 (opened 2026-10-02). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The finding was adjudicated as a false positive and fixed earlier, but it fired again on a solo-owned repo, because non-gatherer facts default to review expected and the PRRD match is case sensitive. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:26:04+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-07: issue 327 state seen via gh: CLOSED. Symptom already fixed by afc12884 (pr_review_expected default False; PRRD slug casefolded) with tests in tests/test_github_config_audit.py; no change in batch B5. Intended move to complete (met before this card) REFUSED by trddgrep move: 'EMMXG7GW has NO acceptance checklist, so archiving it as complete would record a completion that proves nothing: nothing states what the card promised or whether it delivered. Write the checklist first, then archive'. Card stays in todo.
- 2026-10-07T07:50:36+0200 — COMPLETE by main-agent@ai-maestro-janitor. issue 327 closed; both acceptance items met before this card by afc12884.

## Acceptance

- [x] GHCFG-001 does not fire from facts the gatherer did not build (pr_review_expected defaults False) — met before this card: afc12884; tests: test_no_pr_review_silent_for_facts_that_never_resolved_the_builder_verdict (tests/test_github_config_audit.py), test_fix_path_does_not_select_no_pr_review_for_unresolved_facts (tests/test_github_config_fix.py)
- [x] PRRD slug match is case-insensitive — met before this card: afc12884; test: test_prrd_local_match_is_case_insensitive (tests/test_branch_protection_guard.py)
2026-10-07: both boxes ticked; evidence is afc12884 plus the named tests (read in tests/, names verified by grep).
