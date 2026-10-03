---
trdd-id: 7X9WXDK9
title: Task list carried into the new session after a janitor clear
column: backburner
status: tasked
created: 2026-10-03T03:41:49+0200
updated: 2026-10-03T03:45:31+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:41:49+0200
project-id: ai-maestro-janitor
review-after: 2026-10-17
parent-trdd: K9AHY1ZB
derived: true
---

# Task list carried into the new session after a janitor clear

- **C3**: copy the task directory only when all of these hold:
  - this is a janitor chain (a sidecar exists);
  - `CLAUDE_CODE_TASK_LIST_ID` is unset;
  - the old directory holds `*.json` (the file backend, not storageV5);
  - the new directory is empty.

  Skip `*.lock`, keep `.highwatermark`, and label it as relying on undocumented internals. Tests: copy, lock skipped, no overwrite, env set, no sidecar.

Parent plan: TRDD-K9AHY1ZB

## Approval log

- 2026-10-03T03:41:49+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
