---
trdd-id: V6USCGC9
title: cmd_capture advances live_fp but keeps the old live_email when the roles lookup fails, defeating the F5 reconcile
column: complete
created: 2026-09-24T08:11:44+0200
updated: 2026-09-27T12:40:17+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T08:11:44+0200
implementation-commits: [88b10297]
status: archived
---

# cmd_capture advances live_fp but keeps the old live_email when the roles lookup fails, defeating the F5 reconcile

in cmd_capture (rotator.py:1541-1591), when account_email(blob) returns None, the fallback sets state["live_fp"] = fp and saves while live_email stays the OLD account. On the next tick _reconcile_live_email's "already in sync" guard (the F5 fix, TRDD-7PYTX4E9) sees matching fps and never corrects the mislabel. Reported by the ai-maestro Claude (their #22); confirmed. Fix: on a failed lookup, leave state untouched, the same rule F5 applies.

## Approval log

- 2026-09-24T08:11:44+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-24T11:21:36+0200 — column → testing by janitor-main-session. fix landed in 88b10297 with a failing-first test; awaiting the release
- 2026-09-27T12:40:17+0200 — COMPLETE by user. owner batch acceptance 2026-09-27 ('complete all TRDDs'); independent lean-worker verdict DONE before checklist written.

## Acceptance

- [x] test_cmd_capture_leaves_state_untouched_when_account_unresolvable passes on HEAD
- [x] carried in every release since v3.6.0 (tags v3.6.0..v3.6.3 contain the commit)
