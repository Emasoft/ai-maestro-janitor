---
trdd-id: VN2ASDKJ
title: One late rotator tick under load raises the tick-stalled alarm and the doctor remedy
column: todo
status: tasked
created: 2026-10-07T05:15:51+0200
updated: 2026-10-07T05:15:51+0200
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
