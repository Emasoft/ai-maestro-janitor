---
trdd-id: LX5YZOX9
title: Heartbeat coverage after a reboot depends on a fire happening to arrive
column: todo
status: tasked
created: 2026-10-05T22:11:18+0200
updated: 2026-10-05T22:13:34+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:18+0200
---

# Heartbeat coverage after a reboot depends on a fire happening to arrive

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

After the reboot of 2026-10-05 the session re-armed its heartbeat only when resumed. The gap between boot and the first fire was not measured, and the cron id on disk named a cron that no longer existed.

## Approval log

- 2026-10-05T22:11:18+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Corrections

2026-10-05 (review): the statement that the cron id on disk named a cron that no longer existed is WRONG: deleting that id succeeded, so the cron existed in the resumed session. What stays open is the unmeasured gap between boot and the first fire.
