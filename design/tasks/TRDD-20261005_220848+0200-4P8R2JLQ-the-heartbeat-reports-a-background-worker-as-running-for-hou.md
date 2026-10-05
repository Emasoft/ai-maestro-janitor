---
trdd-id: 4P8R2JLQ
title: The heartbeat reports a background worker as running for hours after it stopped
column: todo
status: tasked
created: 2026-10-05T22:08:48+0200
updated: 2026-10-05T22:08:48+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:48+0200
---

# The heartbeat reports a background worker as running for hours after it stopped

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed: for about eight hours every heartbeat fire printed '1 background worker running; newest activity N h ago', and two resume cues named a worker to resume through SendMessage. The worker was not among the session's live agents. Its entry in pending-agents.json carried stopped false and three nudges. To do: find why a finished or dead worker stays listed, when an entry is dropped, and whether the count line should exclude an entry with no activity for hours.

## Approval log

- 2026-10-05T22:08:48+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
