---
trdd-id: 6CF3L7IJ
title: A daemon task ran for 731 seconds against a 30 second foreground budget
column: todo
status: tasked
created: 2026-10-05T22:11:20+0200
updated: 2026-10-07T14:51:20+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:20+0200
---

# A daemon task ran for 731 seconds against a 30 second foreground budget

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

session-liveness took 731 s and a rotator tick 717 s on 2026-10-05. The budget is only reported after the fact. Decide which tasks get a hard time limit. Related: TRDD-JY0OBQZ4.

## Approval log

- 2026-10-05T22:11:20+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Corrections

2026-10-05 (review): the 717 s tick and the 731 s task ended together at 21h33 and belong to one stall, not two independent overruns.
2026-10-07: the overrun watchdog shipped in 3.8.7 (commits 3904fe81, 4dd4e3b6, 7dddf719): it logs 'task X still running after N s' and keeps a pid stamp file while a task is over budget. The bounded-subprocess-wait fix is deferred on advice, because a host-wide freeze fits the 2026-10-05 evidence as well as one blocked call. The next stall decides: if the stamp file keeps refreshing every 5 s, one call was blocked (build the bounded wait); if it stops refreshing, the whole daemon froze (investigate host-level causes instead).
