---
trdd-id: NEVQOHGS
title: Heartbeat and chore token cost must be measured per fire and reported weekly
column: todo
created: 2026-09-16T09:45:04+0200
updated: 2026-09-16T09:45:04+0200
current-owner: session
created-by: session
task-type: infra
min-approval-requirement: none
assignee: session
mandate: true
mandated-by: none
approved: true
approval-judge: session
approval-datetime: 2026-09-16T09:45:04+0200
parent-trdd: V3BQT7QE
---

# Heartbeat and chore token cost must be measured per fire and reported weekly

Symptom: heartbeat and memory-chore token cost is not measured anywhere, so the owner cannot tell how much of the session budget the janitor itself consumes.

Evidence: GitHub #290; owner complaint 2026-09-15 ("chron beats wasting tokens"); parent measured 284 heartbeat fires (this repo, 2026-09-08..15) and 801 fires fleet-wide with no per-fire cost figure recorded anywhere.

## Acceptance criteria
- [ ] Each heartbeat/chore fire appends a tokens-in/tokens-out line to .janitor/logs/heartbeat-cost.log, derived from the transcript the fire ran in -- verified by a test asserting the log file gains exactly one line per simulated fire with two positive integers.
- [ ] A weekly summary command/script sums the 7-day log and reports a single total token count -- verified by a test with >=2 fake week-old log lines asserting the printed total equals their sum.
- [ ] The weekly summary names the top 3 costliest fire kinds (e.g. memory-consolidate, resume, plain-quiet) by summed token spend -- verified by a test with fires of 3+ distinct kinds asserting the top-3 ranking is correct by summed cost.

## Approval log

- 2026-09-16T09:45:04+0200 — MANDATE issued by session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
