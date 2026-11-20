---
trdd-id: 0XCWPWDK
title: A background agent that stops making progress sends no notification and the session waits on it for hours
column: todo
status: tasked
created: 2026-11-19T23:45:17+0100
updated: 2026-11-20T00:25:16+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-19T23:45:17+0100
---

# A background agent that stops making progress sends no notification and the session waits on it for hours

2026-11-19: four background workers (a hook writer and three B607 batches) stopped changing files at about 15:54 and sent no completion notification; the main session ended turns waiting for them until about 22:35. A memory atomize agent stalled right after its claim step at 15:54:20 (its report stayed header-only) and was still listed as running at 23:40. The heartbeat's background-worker line says 'N background workers running; newest activity under 1 min ago' and counted these as live. Fix: the janitor's pending-agent check should flag a registered background agent whose output and owned files have not changed for a bound (e.g. 20 minutes) as STALLED in the heartbeat output, naming it, so the session stops or respawns it. Find how 'newest activity' is computed and why it read these as active.

## Approval log

- 2026-11-19T23:45:17+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Symptom

2026-11-20 data point: a heartbeat fire printed '2 background workers running; newest activity under 1 min ago' while the main agent had at least five background agents in flight (at that fire: lane P, V57FEWSK, 4K7V0GFW, the B105 scripts worker and the B108 tests worker; the handoff follow-up and the relocate chore were spawned after it). The worker count the heartbeat reports undercounts; cause not measured.
