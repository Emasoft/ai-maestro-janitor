---
trdd-id: O66GZTWE
title: Singleton chores pass between the daemon and the ai-maestro server several times in one evening
column: blocked
status: tasked
created: 2026-10-05T22:08:50+0200
updated: 2026-10-10T15:30:38+0200
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
blocked-by: [NBIFKLLC]
pre-block-column: todo
---

# Singleton chores pass between the daemon and the ai-maestro server several times in one evening

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed in the daemon log: 'server no longer confirmed active - resuming singleton chores' at 18:28 and 20:45 (liveness stamp 138 s and 103 s old), and 'yielding to active ai-maestro server' at 21:40 for a list that includes memory-guard and version-update. Under load the liveness stamp goes stale and ownership moves back and forth. To do: measure how often it flips, check whether a chore can run twice or not at all across a flip, and decide whether safety chores such as memory-guard should be yielded at all.

## Approval log

- 2026-10-05T22:08:50+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Findings

2026-10-10 15:30, wave 10 card 1, measured by the main session in the daemon log (retained span 2026-10-07 18:24 to 2026-10-10 15:30, two files). (1) HOW OFTEN: 32 'resuming singleton chores' and 34 'yielding' lines in that span, 8 of each on 2026-10-10; the resume lines sampled carry a liveness age of 92 to 148 s against a threshold of 90 s (harness_backend.LIVENESS_STALE_AFTER_S; the server rewrites the stamp every 30 s), and the daemon yields again 20 to 60 s later. So a flip is the server missing two to four stamps, not the server stopping. (2) TWICE OR NOT AT ALL: inside those resume windows the daemon started fleet-stop 36 times and memory-guard 26 times, each done in 0 to 4 s, and started version-update, cache-prune, fleet-plugins-update and github-config-audit zero times. Whether the server ran the same chore at the same moment is NOT observable from this log, and no chore was shown to be skipped. No harm is observed. (3) WHETHER SAFETY CHORES SHOULD BE YIELDED: NOT DECIDED here. Which chores the server claims is the server's list, and what prevents a double run across a flip is the per-chore lease of the joint handover spec, whose formats are the open questions of proposal TRDD-NBIFKLLC; the question 'should memory-guard be claimed by the server at all' is added there. OBSERVER for a harmful flip: any start line of version-update, cache-prune, fleet-plugins-update or github-config-audit between a resume line and the next yield line in daemon.log.
