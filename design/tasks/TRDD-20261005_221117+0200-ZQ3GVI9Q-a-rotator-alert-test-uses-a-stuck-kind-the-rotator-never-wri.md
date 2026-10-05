---
trdd-id: ZQ3GVI9Q
title: A rotator alert test uses a stuck kind the rotator never writes
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

# A rotator alert test uses a stuck kind the rotator never writes

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

tests/test_rotator_alert.py writes kind 'all-exhausted'; the rotator writes five other names. The test passes on a value production never produces.

## Approval log

- 2026-10-05T22:11:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
