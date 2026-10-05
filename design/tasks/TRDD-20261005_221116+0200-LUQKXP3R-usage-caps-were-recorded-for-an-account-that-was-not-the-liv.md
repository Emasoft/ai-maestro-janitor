---
trdd-id: LUQKXP3R
title: Usage caps were recorded for an account that was not the live one
column: todo
status: tasked
created: 2026-10-05T22:11:16+0200
updated: 2026-10-05T22:11:16+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:16+0200
---

# Usage caps were recorded for an account that was not the live one

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

The rotator state on 2026-10-05 held five 5h and five 7d cap samples of 0.0 for an alternate account. Cap learning runs only for the live account, so how these were written was never explained.

## Approval log

- 2026-10-05T22:11:16+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
