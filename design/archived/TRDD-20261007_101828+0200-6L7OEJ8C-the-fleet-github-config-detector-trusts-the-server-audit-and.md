---
trdd-id: 6L7OEJ8C
title: The fleet GitHub-config detector trusts the server audit and re-raises NO_PR_REVIEW on repos whose own rule says no pull request
column: complete
status: archived
created: 2026-10-07T10:18:28+0200
updated: 2026-10-10T23:12:23+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T10:18:28+0200
---

# The fleet GitHub-config detector trusts the server audit and re-raises NO_PR_REVIEW on repos whose own rule says no pull request

## Symptom

2026-10-07 10:14 the heartbeat printed a GHCFG-001 NO_PR_REVIEW ticket for Emasoft/ai-maestro-janitor and wrote proposal TRDD-0JTGLSXE, although issue 327 (TRDD-EMMXG7GW, commit afc12884) was closed as fixed and this repo's PRRD says require-pull-request: false.

## Cause (VERIFIED by reading the code and both findings files)

scripts/detectors/fleet-github-config.py::_read_findings takes the newer of two files: the janitor daemon's own findings file in the plugin global-state folder (generated 2026-10-04, zero findings) and the ai-maestro server's copy in the server's home folder (generated 2026-10-07 09:49, NO_PR_REVIEW on all 14 fleet repos). The server's audit does not apply the 2026-08-13 owner ruling that branch_protection_lib.require_pull_request_for encodes, and the detector surfaces its findings unfiltered. The fix path the ticket offers would re-impose the pull_request rule the ruling removed.

## Task

In the detector, before surfacing or proposing a NO_PR_REVIEW finding for the current repo, drop it when require_pull_request_for(slug) is False. Failing test first: a server findings file newer than the local one that carries NO_PR_REVIEW for the current repo, with the repo's PRRD saying false, yields no line and no proposal; with the PRRD saying true it still does.
2026-10-07 review additions, part of this task: (1) apply the predicate to EVERY slug the detector surfaces or proposes for, in one place, and print how many server findings were dropped; (2) an undetermined predicate must NOT drop a finding: require_pull_request_for returns False on an unknown login or any exception, so the detector needs a tri-state (stated false or confirmed own repo = drop; could not determine = keep) with a test for the undetermined case; (3) say what happens to fleet-github-config-seen.txt and the suppressed-count file when a finding is dropped; (4) compare generated_at as numbers when both parse as numbers, since a string compare of an ISO value against an epoch integer ignores time; (5) the claim that the server audit ignores the ruling rests on its output file only, its code was not read. Also noted: the janitor's own findings file is from 2026-10-04 and its audit last-run stamp from July, because the server owns the chore; if the server stops, the detector reads a stale local file with zero findings.
2026-10-07 corrections to the review additions above: (a) per-project rule: filter every slug in the shared path, but print or propose only for the CURRENT repo; the dropped count goes to the ledger, never to the heartbeat line for other repos; (b) an undetermined predicate keeps the finding as an advisory marked undetermined and NEVER writes a fixable proposal for it; (c) a repo whose PRRD cannot be read from here counts as undetermined, not as own-repo-drop; (d) generated_at: when one value is ISO and the other a number, convert both to epoch before comparing; (e) name one test per addition; (f) unread: whether ticket_proposal.py treats a refused card as already proposed, and whether the seen-file's content hash changes on every server audit; until this card ships the heartbeat may print the ticket line again.

## Not in this card

- The server audit itself lives in the ai-maestro repo; it needs an issue there (not filed yet, the owner has not been asked).
- Proposal TRDD-0JTGLSXE is a false finding and must not be approved.
- _read_findings' comment says generated_at is ISO-8601; both files carry epoch integers. Lexical order still works while the digit count is equal.

## Approval log

- 2026-10-07T10:18:28+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T23:12:23+0200 — COMPLETE by main-agent@ai-maestro-janitor. archived → complete.

## Acceptance

- [x] A NO_PR_REVIEW finding is dropped where the repo's own rule says no pull request, and still raised where it says true: commits ba7f26c1, bd80987f, 3904fe81, all in release v3.8.7; tests test_no_pr_review_is_dropped_when_the_repos_own_prrd_says_false and test_no_pr_review_is_still_raised_when_the_repos_own_prrd_says_true.
- [x] Review additions 1, 2, 4 and corrections a, b, d, each with a named test: every slug filtered in one place with the drop count in the detector's log, never printed for other repos (test_other_repos_are_filtered_but_never_printed_and_the_drop_count_goes_to_the_log); an undetermined requirement keeps an advisory and never proposes (test_an_undetermined_requirement_keeps_an_advisory_and_never_proposes); generated_at compared as time (test_generated_at_is_compared_as_time_not_as_text). NARROWED: correction c (a repo whose rule cannot be read counts as undetermined) is covered only through the tri-state test, no test of its own was looked for; addition 3 (what happens to the seen file and the suppressed count on a drop) was answered in code only as far as line 311, the digest is taken from the payload after the drop; the suppressed-count file was not read.
- [x] FIELD CASE OBSERVED, the card's own: this project's fleet-github-config.log holds 95 lines 'dropped 1 NO_PR_REVIEW finding(s): pull-request requirement determined false' from 2026-10-07 14:39:35 to 2026-10-10 23:11:19 (installed version 3.8.11), and the findings ledger holds one GHCFG-001 entry, the original of 2026-10-07 10:14, none since; the false proposal TRDD-0JTGLSXE is in column refused. All 28 tests of tests/test_fleet_github_config_detector.py passed on a re-run by the main session at this time.

## STATE

2026-10-10 23:12. CLOSED to complete by the main session: the fix was built and released on 2026-10-07 and the card was left in todo. NOT READ, and not needed for the closing: the two questions of correction f (whether ticket_proposal treats a refused card as already proposed; whether the seen file's hash changes on every server audit); no ticket line recurred, which is the outcome they guarded. STILL OPEN OUTSIDE THIS CARD, the owner's: the server audit in the ai-maestro repository does not apply the 2026-08-13 ruling and needs an issue there; nothing was posted. Also unchanged: if the server stops owning the chore, the detector reads the janitor's own findings file of 2026-10-04.
