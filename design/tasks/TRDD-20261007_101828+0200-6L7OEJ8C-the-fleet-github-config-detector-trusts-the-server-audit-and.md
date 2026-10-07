---
trdd-id: 6L7OEJ8C
title: The fleet GitHub-config detector trusts the server audit and re-raises NO_PR_REVIEW on repos whose own rule says no pull request
column: todo
status: tasked
created: 2026-10-07T10:18:28+0200
updated: 2026-10-07T10:20:35+0200
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
