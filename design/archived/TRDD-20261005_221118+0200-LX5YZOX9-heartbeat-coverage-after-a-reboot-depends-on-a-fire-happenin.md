---
trdd-id: LX5YZOX9
title: Heartbeat coverage after a reboot depends on a fire happening to arrive
column: complete
status: archived
created: 2026-10-05T22:11:18+0200
updated: 2026-10-10T17:03:11+0200
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
release-via: none
---

# Heartbeat coverage after a reboot depends on a fire happening to arrive

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

After the reboot of 2026-10-05 the session re-armed its heartbeat only when resumed. The gap between boot and the first fire was not measured, and the cron id on disk named a cron that no longer existed.

## Approval log

- 2026-10-05T22:11:18+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T17:03:11+0200 — COMPLETE by main-agent@ai-maestro-janitor. archived → complete.

## Corrections

2026-10-05 (review): the statement that the cron id on disk named a cron that no longer existed is WRONG: deleting that id succeeded, so the cron existed in the resumed session. What stays open is the unmeasured gap between boot and the first fire.
2026-10-10 17:03. MEASURED, no code (wave 14 card 2). Boot of 2026-10-05 at 21:43:09 (kern.boottime). In .janitor/logs/heartbeat-fires.log the last fire before it is at 21:39:22 and the first after it at 21:59:05, both of session 1f607a9a. That session's transcript has no entry between 21:34:01 and 21:58:58, so the session was resumed 15.8 minutes after boot and its first fire came 7 seconds later. The whole gap is the time until the owner resumed the session; the heartbeat is a cron inside a Claude session and cannot fire while no session runs. Chores that must run with no session belong to the daemon (a LaunchAgent), which this card does not concern. DECISION: nothing to fix. NOT CHECKED: whether the daemon itself was up between boot and the resume; whether the 7-second fire came from the SessionStart re-arm or from the resumed cron (the 2026-10-05 correction says the old cron id still existed). One reboot measured, one project.

## Acceptance

- [x] The gap between boot and the first fire is measured: 15.9 minutes, of which 15.8 passed before the session was resumed. NARROWED: one reboot, one project; no fix, by decision.
