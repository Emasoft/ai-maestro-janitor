---
trdd-id: 366Y1OUH
title: A give-up for a non-frozen diagnosis writes no findings entry
column: todo
status: tasked
created: 2026-10-17T01:59:59+0200
updated: 2026-10-17T01:59:59+0200
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
approval-datetime: 2026-10-17T01:59:59+0200
---

# A give-up for a non-frozen diagnosis writes no findings entry

Split from TRDD-393Z256I (59fb90d0). In scripts/daemon.py task_session_liveness, the crash_loop branch (~l.1698-1721) records a findings entry (HEARTBEAT-FIRES-STALL) only for diagnosis frozen; for cron_dead, version_mismatch and others the give-up 'GIVING UP ... a human must intervene' writes only a daemon.log line and one audit row, so it reaches no surface the owner reads. To do: record one findings entry per give-up for every diagnosis (deduped by the existing alerted flag), with a remedy text; test it.

## Approval log

- 2026-10-17T01:59:59+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
