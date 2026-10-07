---
trdd-id: ZQ3GVI9Q
title: A rotator alert test uses a stuck kind the rotator never writes
column: complete
status: archived
created: 2026-10-05T22:11:17+0200
updated: 2026-10-07T07:01:44+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:17+0200
implementation-commits: [33734cd6]
---

# A rotator alert test uses a stuck kind the rotator never writes

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

tests/test_rotator_alert.py writes kind 'all-exhausted'; the rotator writes five other names. The test passes on a value production never produces.

## Approval log

- 2026-10-05T22:11:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T07:01:44+0200 — COMPLETE by main-agent@ai-maestro-janitor. resolved, evidence in STATE.

## STATE

2026-10-07 merged on main (33734cd6): the test uses no-usable-slot-twin, a kind the rotator writes in _mark_stuck, and asserts the alert text; the value all-exhausted appears nowhere under scripts/, so no dead branch remains.

## Acceptance checklist

- [x] The test uses no-usable-slot-twin, a kind written by _mark_stuck, and asserts the alert text; all-exhausted appears nowhere under scripts/; merged 33734cd6; pytest 18087 passed, 2 skipped on main at the B3 merge.
