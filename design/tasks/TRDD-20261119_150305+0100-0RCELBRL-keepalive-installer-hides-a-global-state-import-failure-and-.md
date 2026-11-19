---
trdd-id: 0RCELBRL
title: keepalive installer hides a global_state import failure and silently falls back to the DATA log dir
column: backburner
status: tasked
created: 2026-11-19T15:03:05+0100
updated: 2026-11-19T15:03:05+0100
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
approval-datetime: 2026-11-19T15:03:05+0100
---

# keepalive installer hides a global_state import failure and silently falls back to the DATA log dir

keepalive_install.sh resolve_log_dir (line 148-157) runs the global_state import with 2>/dev/null and on any failure prints GS_DATA_DIR. A broken staged closure (proved 2026-11-19: global_state.py + state.py without exe_path.py gives ModuleNotFoundError exe_path) therefore installs launchd/systemd log capture into a different dir than the daemon logs into, with no message. Found while tracing the test_launchd_keepalive regression from f8cddea9 (TRDD-SWQXCIOS). Fix: let the import error reach stderr (or record a finding) and distinguish 'no staged closure yet' (legitimate fallback) from 'closure present but import fails' (fail loudly). PRRD G34.1.

## Approval log

- 2026-11-19T15:03:05+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
