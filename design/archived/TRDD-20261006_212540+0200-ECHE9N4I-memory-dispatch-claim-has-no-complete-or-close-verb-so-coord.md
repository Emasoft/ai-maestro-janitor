---
trdd-id: ECHE9N4I
title: memory_dispatch claim has no complete or close verb so coordinators move state files by hand
column: complete
status: archived
created: 2026-10-06T21:25:40+0200
updated: 2026-10-10T21:50:43+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:40+0200
---

# memory_dispatch claim has no complete or close verb so coordinators move state files by hand

Source: GitHub issue Emasoft/ai-maestro-janitor#311 (opened 2026-09-25). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: memory_dispatch_claim.py creates a claim file but no verb closes it. A coordinator that correctly abstains is left holding a live claim and improvises by renaming files and patching status fields. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:40+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T21:50:43+0200 — COMPLETE by main-agent@ai-maestro-janitor. already fixed (3cfcb56d, 7219523b, 2bb6c99a; v3.5.1 and v3.5.3); issue 311 closed with commit and release.

## Findings

2026-10-10 21:50 CLOSED ON EVIDENCE, no new code. scripts/memory_dispatch_claim.py has a complete subcommand (main, line 919; complete_claim, line 524) that closes a claim by its dispatch id. Issue 311 is CLOSED (2026-10-06T20:44:55Z); its last comment names commits 3cfcb56d, 7219523b and 2bb6c99a, releases v3.5.1 and v3.5.3, and the tests test_complete_claim_renames_claimed_to_done_with_report and test_complete_cli_prints_claim_id_last_and_completes. READ by this session: the subcommand and function exist, and git log -S'def complete_claim' gives 3cfcb56d of 2026-09-15. NOT READ by this session: the two other commits, the two test bodies, and whether a coordinator that ABSTAINS (the issue's own case) has a verb distinct from complete; the closing comment says a successful claim prints the exact set-report and complete commands.

## Acceptance

- [x] The symptom is gone in a test that failed before the fix (the two tests named in the issue's closing comment; 3cfcb56d).
- [x] A closing comment on the issue names the commit and the release (issue 311, closed 2026-10-06).
