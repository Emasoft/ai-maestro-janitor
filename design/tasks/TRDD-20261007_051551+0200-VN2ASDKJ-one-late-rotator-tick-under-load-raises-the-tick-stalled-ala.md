---
trdd-id: VN2ASDKJ
title: One late rotator tick under load raises the tick-stalled alarm and the doctor remedy
column: backburner
status: tasked
created: 2026-10-07T05:15:51+0200
updated: 2026-10-10T22:45:13+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T05:15:51+0200
parent-trdd: JOXQQL4J
review-after: 2026-12-10
---

# One late rotator tick under load raises the tick-stalled alarm and the doctor remedy

## Problem
Observed under very high load (from TRDD-JOXQQL4J): one rotator tick took 717 s, and the next heartbeat told the owner the account rotator had stopped ticking and to run the doctor, although the rotator ticked normally a minute later. Since 9377073e a stalled ps makes the alert evaluation run where it used to skip, so the alarm is evaluated exactly when ticks are late.

## To do
Compare TICK_STALL_S in scripts/lib/rotator_alert.py with measured tick durations under load and decide whether the alarm needs a second consecutive miss.

## Acceptance
- [ ] One test where a single late tick does not raise the alarm and a real stop does.

## Approval log

- 2026-10-07T05:15:51+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-10 03:48 from the closure of TRDD-JOXQQL4J (archived): its third Acceptance box was ticked for the question this card carries, which was handed over, not answered. FIELD CASE UNOBSERVED for the alert-evaluation path: nine handled stalled-ps ticks were seen on the tick path only; the daemon's stderr file (global-state/daemon-keepalive.err.log) is 115 bytes since the re-stage of 2026-10-09 and holds no handled-stall line.

## STATE

2026-10-10 22:45. MEASURED, PROPOSED, NOT BUILT; parked in backburner by decision of the main session under the mandate of 2026-10-09. MEASURED on this machine's daemon.log and daemon.log.1 (2218 completed ticks, 2026-10-09 07:29 to 2026-10-10 22:41; reports/board/20261010_224359+0200-vn2asdkj-measure.md): tick duration median 1 s, 99th percentile 63 s, maximum 192 s (seven ticks above 120 s); gap between completed ticks median 61 s, none above 300 s; the alarm text ('tick-stalled' or 'stopped ticking') appears 0 times in those two logs and in this project's dispatch.log. The 717 s tick is known only from the prose of the archived TRDD-JOXQQL4J ('Found on 2026-10-05'); no log line for it is retained. CODE FACTS: two thresholds of 600 s, TICK_STALL_S (scripts/lib/rotator_alert.py:29, read by the daemon's alert evaluation and by the session-side drift line) and TICK_STALL_ALERT_S (scripts/oauth_rotator/supervisor.py:52, default overridable by ROTATOR_TICK_STALL_ALERT_S); the completion stamp is written in the finally of cmd_tick (rotator.py:3599), so a no-op beat and a tick that raises both stamp, and only a hang leaves it stale; the rotator writes no tick-start stamp. PROPOSED and WITHDRAWN: raising both thresholds to 1200 s. REVIEW BLOCKERS ACCEPTED: 1200 was chosen only for being above 717 and nothing bounds the next slow tick; 717 s is a tick's duration while the alarm compares the stamp's age, which was higher and never measured, so a test at 717 s may not reproduce the field case; a threshold cannot tell slow from stopped, whereas 'no alarm while a tick is in flight and younger than a bound' can, and keeps the 600 s detection for a tick that never starts. THAT DESIGN IS NOT BUILT: it needs a new start stamp in the rotator's tick and changes in both readers and their tests, for one instance no log retains. The card's own idea, a second consecutive miss, has no meaning beyond the stamp's age. PULL CONDITION, checkable: a tick line 'done in N s' with N at or above 600 in the daemon log, or the alarm text in the daemon log or in a dispatch.log. DETECT: grep -a -h -c 'tick-stalled' <global-state>/daemon.log <global-state>/daemon.log.1 (0 today). Acceptance box stays open.
