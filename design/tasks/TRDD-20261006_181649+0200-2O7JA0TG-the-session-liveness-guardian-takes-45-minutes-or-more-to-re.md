---
trdd-id: 2O7JA0TG
title: The session-liveness guardian waits three heartbeat intervals before re-arming a session left with no heartbeat after a clear
column: backburner
status: tasked
created: 2026-10-06T18:16:49+0200
updated: 2026-10-10T22:41:34+0200
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
review-after: 2026-12-10
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
2026-10-06: related: since 79255d6e an idle session with a live cron can be re-engaged by the keep-going nudge, once per board state and only when its conditions hold (a stale pending agent, or no agents plus an open dev/todo card); this card remains for the cron-less case only (guardian latency).
2026-10-10 22:40. MEASURED, PROPOSED, NOT BUILT; parked in backburner by decision of the main session under the mandate of 2026-10-09. MEASURED in this project only (heartbeat-fires.log against session-start.log, 153 clears since 2026-08-05): the next fire logged in the project came within 900 s for 148 clears and within 1200 s for 149 (119 within 60 s, which are mostly the bootstrap's own arm and resume runs, not cron fires); 4 clears (2026-09-03 12:22, 2026-09-26 16:45, 2026-10-08 06:11, 2026-10-09 09:40) were followed by 4.5 to 9.4 hours with no fire and silent logs, cause undecided (reports/board/20261010_223905+0200-2o7ja0tg-measure.md). PROPOSED: when clear-observed.ts is newer than the last fire, use min(normal, max(1200, period + 300 + period/10)) seconds, which is 1290 s at the default cadence, not the 1200 s the proposal stated. REVIEW BLOCKERS ACCEPTED: (a) the stamp and the fire log are per project while the diagnosis is per session, so one session's clear would put a healthy sibling session under the short window, a needless re-arm of the kind the owner banned; the fire lines carry a session id but how diagnose_root learns its instance's session id was not read; (b) the measurement is a project-level fire gap, not the transcript age the code compares; a long foreground tool call, an open dialog or a sleep after a clear leaves a live cron with a stale transcript, and cron-only gaps were not measured; (c) a manual stub run logs a fire too, so a cron-less session that ran the resume command once keeps the long window, which misses part of this card's own case; (d) the case of a clear stamp with an empty fire log was unspecified. REVIEW BLOCKER REFUTED by the card's own figures: 'the window may not be the binding term' does not hold for the field case, clear 15:35:05 plus 45 minutes is 16:20 and the re-arm fired at 16:26:14, so the window was about 45 of the 51 minutes. NOT EXPLAINED: why the session-start CronList self-check, printed on every clear, did not cure the field case (it acts only when the model next takes a turn; whether that session took one is in another project's transcript, which the main session does not read until the owner answers TRDD-XDH7KPK2). WHY PARKED: one field case in another project, a saving of about 25 minutes of an idle session without a heartbeat, against a new false re-arm path. PULL CONDITION: a second occurrence in this project (a session-start line 'source=clear keeps the live cron' followed by a guardian 'FIRED rearm' with cron_dead for the same session), or the owner allowing the read under TRDD-XDH7KPK2. A build then needs: per-session matching of clear and fire, transcript-entry gaps measured after clears, and the empty-log case decided.
2026-10-10 22:41. CORRECTIONS from the review of 40a92aba, accepted. (1) 'mostly the bootstrap's own arm and resume runs' was not measured; read it as likely, unmeasured. (2) The refutation of 'the window was not the binding term' assumes the transcript last advanced at the clear of 15:35:05, which is in another project's transcript and unverified; read it as contradicted by the card's figures if the transcript stopped at the clear. (3) The pull condition names a guardian log line whose file and exact text were not read; and the 4 long gaps in this project show a clear followed by hours of silence with no re-arm found, a case that condition cannot see. SECOND PULL CONDITION: a clear in this project followed by more than 45 minutes without a fire while the session's process is alive. (4) The in-project measurements the proposal's review asked for (transcript-entry gaps after clears, cron-only fires, how diagnose_root learns a session id) were runnable today and were not run; they are the first steps when the card is pulled.
