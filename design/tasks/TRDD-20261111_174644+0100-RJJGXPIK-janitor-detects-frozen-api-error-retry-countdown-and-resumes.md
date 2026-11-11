---
trdd-id: RJJGXPIK
title: janitor detects frozen API-error retry countdown and resumes
column: dev
status: tasked
created: 2026-11-11T17:46:44+0100
updated: 2026-11-11T17:50:24+0100
current-owner: user
created-by: user
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: user
mandate: true
mandated-by: none
approved: true
approval-judge: user
approval-datetime: 2026-11-11T17:46:44+0100
relevant-rules: [1]
---

# janitor detects frozen API-error retry countdown and resumes

## Approval log

- 2026-11-11T17:46:44+0100 — MANDATE issued by user (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-11T17:50:24+0100 — column → dev by user. owner directive: implement freeze recovery now

## STATE

CURRENT (2026-11-11) — TRDD-A created. External freeze recovery: frozen-countdown confirm (retry_in byte-identical across polls >=120s, only with second-granularity), API_ERROR positional anchor, post-ESC resume injection with settle delay + episode timeout. Review findings accepted. Implementation pending.
