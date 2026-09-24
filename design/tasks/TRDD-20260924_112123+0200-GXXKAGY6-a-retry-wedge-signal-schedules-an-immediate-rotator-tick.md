---
trdd-id: GXXKAGY6
title: A retry-wedge signal schedules an immediate rotator tick
column: todo
created: 2026-09-24T11:21:23+0200
updated: 2026-09-24T11:29:24+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T11:21:23+0200
---

# A retry-wedge signal schedules an immediate rotator tick

Release 1 of TRDD-RAEGS1D5; item (f) and term D7 on TRDD-4XND73XD. When the 429 retry-wedge is detected, schedule a rotator tick now instead of waiting for the 60 s beat; the tick still respects the usage cache, the cooldown and at most one per MIN_DWELL_S. Acceptance: a test that fails without it.

## Approval log

- 2026-09-24T11:21:23+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Review corrections 2026-09-24

Open decision, to settle before code: how the wedge signal counts against LIVE_429_DEBOUNCE. An immediate tick that still waits out the debounce saves only one beat. Scope stays within term D7 of TRDD-4XND73XD (a trigger only schedules a tick). Counting a wedge as a debounced 429 would amend D7 and needs the ai-maestro Claude's agreement first. Test: a wedge signal starts a tick before the next scheduled 60 s beat, and a second signal inside MIN_DWELL_S starts none.
