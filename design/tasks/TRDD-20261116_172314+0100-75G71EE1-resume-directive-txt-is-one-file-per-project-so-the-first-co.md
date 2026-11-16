---
trdd-id: 75G71EE1
title: resume-directive.txt is one file per project so the first consuming session wins
column: todo
status: tasked
created: 2026-11-16T17:23:14+0100
updated: 2026-11-16T17:23:14+0100
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
approval-datetime: 2026-11-16T17:23:14+0100
---

# resume-directive.txt is one file per project so the first consuming session wins

The resume directive pointer in .janitor/state is not keyed by session, so when several sessions share a project the first session to consume it takes another session's directive. Found during TRDD-W6DZPXLG research, not re-verified.

## Approval log

- 2026-11-16T17:23:14+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
