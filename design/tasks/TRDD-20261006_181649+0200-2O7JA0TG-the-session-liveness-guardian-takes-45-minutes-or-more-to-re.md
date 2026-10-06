---
trdd-id: 2O7JA0TG
title: The session-liveness guardian waits three heartbeat intervals before re-arming a session left with no heartbeat after a clear
column: todo
status: tasked
created: 2026-10-06T18:16:49+0200
updated: 2026-10-06T18:44:49+0200
current-owner: main-agent@ai-maestro-janitor
created-by: lean-worker#cd372946-645f-4e16-a8a0-7013e0d8c5b6
task-type: bugfix
min-approval-requirement: none
assignee: lean-worker#cd372946-645f-4e16-a8a0-7013e0d8c5b6
mandate: true
mandated-by: none
approved: true
approval-judge: lean-worker#cd372946-645f-4e16-a8a0-7013e0d8c5b6
approval-datetime: 2026-10-06T18:16:49+0200
parent-trdd: K60FT7PJ
derived: true
derived-kind: eht
---

# The session-liveness guardian takes 45 minutes or more to re-arm a session left with no heartbeat after a clear

## Problem
A session left with no live heartbeat cron after a clear (failed startup arm, then a clear) is re-armed by the daemon guardian only after the transcript-staleness window, which is 3 x cadence (45 min at a 15 min cadence) plus the typing gate. Detection exists; its latency is the defect.

## Evidence (from reports/continuity-build/20261006_180000+0200-k60ft7pj-ownership-measure.md)
- VERIFIED fleet_scan.py:45 STALE_S and :665-677 stale_threshold_for: stale = max(15 min, 3 x armed cadence).
- VERIFIED daemon.py:1440 task_session_liveness; daemon.py ~1503 typing gate defers every injection while HID idle <= USER_PRESENT_IDLE_S.
- VERIFIED on-session-start.py:1497-1517 'source=clear keeps the live cron -> no re-arm' uses gs.armed_state() (a claim, not a live-cron check); false after a failed startup arm.
- VERIFIED WEBDESIGN 2026-10-06: startup 15:29:14 without arm line, clear 15:35:05, no heartbeat fire 2026-10-05T21:31 to 2026-10-06T17:00, guardian 'FIRED rearm' 16:26:14 [cron_dead] = 51 min idle.
- Constraint: the owner banned needless mid-session re-arms (pre-2026-08-08, 'rearmed randomly in the middle of the sessions'); an unconditional re-arm cue on source=clear is NOT allowed.
- Owner card L32WC0H7 covers rate-limit stalls and cold-cache /clear, not this; no overlap.

## Approval log

- 2026-10-06T18:16:49+0200 — MANDATE issued by lean-worker#cd372946-645f-4e16-a8a0-7013e0d8c5b6 (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

NEXT ACTION (2026-10-06, second): measure how often transcript-staleness false positives would fire with a shorter window when clear-observed.ts is newer than the last heartbeat-fires.log entry; propose the window rule. Constraint: no needless mid-session re-arms.
2026-10-06: the stale window is max(15 min, 3 x cadence) (fleet_scan.py:45, :665-677): 45 min at */15, 15 min at */5; the measured 51 min also includes the typing gate.
