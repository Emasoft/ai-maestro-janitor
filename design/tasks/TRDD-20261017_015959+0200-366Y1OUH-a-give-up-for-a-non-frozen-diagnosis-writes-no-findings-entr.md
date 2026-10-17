---
trdd-id: 366Y1OUH
title: A give-up for a non-frozen diagnosis writes no findings entry
column: testing
status: tasked
created: 2026-10-17T01:59:59+0200
updated: 2026-10-17T02:14:12+0200
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
implementation-commits: [77e52628]
---

# A give-up for a non-frozen diagnosis writes no findings entry

Split from TRDD-393Z256I (59fb90d0). In scripts/daemon.py task_session_liveness, the crash_loop branch (~l.1698-1721) records a findings entry (HEARTBEAT-FIRES-STALL) only for diagnosis frozen; for cron_dead, version_mismatch and others the give-up 'GIVING UP ... a human must intervene' writes only a daemon.log line and one audit row, so it reaches no surface the owner reads. To do: record one findings entry per give-up for every diagnosis (deduped by the existing alerted flag), with a remedy text; test it.

## Approval log

- 2026-10-17T01:59:59+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-17T02:14:10+0200 — BUILT in 77e52628: non-frozen give-ups (cron_dead, version_mismatch, retry_wedged, dead) record one HIGH FLEET-GIVE-UP finding and push one owner notification, once per episode (alerted gate). Texts are descriptive (no commands, no repeat of the failed action, no /reload-plugins) because the ledger is replayed into autonomous sessions. A dead give-up with hard restart off (default) says nothing was relaunched. Historical 283 of 299 give-ups were cron_dead, mostly the false wedged-path ones 59fb90d0 removed; the future rate is unmeasured. OPEN QUESTION (not built): dry-run relaunches still spend attempts at daemon.py _run_hard_restart, and the give-up check reads hard_restart_enabled() only, not the caller fire flag. 57 tests pass; ruff, mypy (scripts/), pyright clean. FIELD CHECK: the next real give-up after a release shows one FLEET-GIVE-UP in that project's replay and one push.
