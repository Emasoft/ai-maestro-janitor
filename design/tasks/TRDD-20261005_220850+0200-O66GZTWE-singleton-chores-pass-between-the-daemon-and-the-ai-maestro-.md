---
trdd-id: O66GZTWE
title: Singleton chores pass between the daemon and the ai-maestro server several times in one evening
column: todo
status: tasked
created: 2026-10-05T22:08:50+0200
updated: 2026-10-05T22:08:50+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:50+0200
---

# Singleton chores pass between the daemon and the ai-maestro server several times in one evening

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed in the daemon log: 'server no longer confirmed active - resuming singleton chores' at 18:28 and 20:45 (liveness stamp 138 s and 103 s old), and 'yielding to active ai-maestro server' at 21:40 for a list that includes memory-guard and version-update. Under load the liveness stamp goes stale and ownership moves back and forth. To do: measure how often it flips, check whether a chore can run twice or not at all across a flip, and decide whether safety chores such as memory-guard should be yielded at all.

## Approval log

- 2026-10-05T22:08:50+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
