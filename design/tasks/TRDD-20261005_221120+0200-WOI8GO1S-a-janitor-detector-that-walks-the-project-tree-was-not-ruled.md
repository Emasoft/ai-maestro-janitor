---
trdd-id: WOI8GO1S
title: A janitor detector that walks the project tree was not ruled out for a project with a very large ignored folder
column: todo
status: tasked
created: 2026-10-05T22:11:20+0200
updated: 2026-10-05T22:11:20+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:20+0200
---

# A janitor detector that walks the project tree was not ruled out for a project with a very large ignored folder

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

In a project holding a folder of more than 100 GB, heartbeat fires were cleared of the 2026-10-05 spikes by timing only. No detector's tree walk was read to confirm that it prunes ignored and oversized folders.

## Approval log

- 2026-10-05T22:11:20+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
