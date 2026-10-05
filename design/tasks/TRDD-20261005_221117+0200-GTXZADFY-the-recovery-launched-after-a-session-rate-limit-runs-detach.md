---
trdd-id: GTXZADFY
title: The recovery launched after a session rate limit runs detached with nobody waiting for its result
column: todo
status: tasked
created: 2026-10-05T22:11:17+0200
updated: 2026-10-05T22:11:17+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:17+0200
---

# The recovery launched after a session rate limit runs detached with nobody waiting for its result

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

The stop-failure hook starts 'rotator.py auto' with both streams discarded and writes a marker for the daemon to retry. The daemon task that serves the marker is a second launcher. Verify that a failed launch is always retried and that its outcome is logged somewhere.

## Approval log

- 2026-10-05T22:11:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
