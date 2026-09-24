---
trdd-id: V6USCGC9
title: cmd_capture advances live_fp but keeps the old live_email when the roles lookup fails, defeating the F5 reconcile
column: todo
created: 2026-09-24T08:11:44+0200
updated: 2026-09-24T08:11:44+0200
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
---

# cmd_capture advances live_fp but keeps the old live_email when the roles lookup fails, defeating the F5 reconcile

in cmd_capture (rotator.py:1541-1591), when account_email(blob) returns None, the fallback sets state["live_fp"] = fp and saves while live_email stays the OLD account. On the next tick _reconcile_live_email's "already in sync" guard (the F5 fix, TRDD-7PYTX4E9) sees matching fps and never corrects the mislabel. Reported by the ai-maestro Claude (their #22); confirmed. Fix: on a failed lookup, leave state untouched, the same rule F5 applies.

## Approval log

- 2026-09-24T08:11:44+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
