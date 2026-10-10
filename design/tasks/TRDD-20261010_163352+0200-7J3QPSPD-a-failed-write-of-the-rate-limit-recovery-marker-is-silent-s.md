---
trdd-id: 7J3QPSPD
title: A failed write of the rate-limit recovery marker is silent so the daemon never retries and nothing records it
column: todo
status: tasked
created: 2026-10-10T16:33:52+0200
updated: 2026-10-10T16:33:52+0200
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
approval-datetime: 2026-10-10T16:33:52+0200
---

# A failed write of the rate-limit recovery marker is silent so the daemon never retries and nothing records it

Found on 2026-10-10 while verifying TRDD-GTXZADFY; read from the code, not observed. In scripts/hooks/on-stop-failure.py the write of recovery-requested.ts sits inside contextlib.suppress(Exception). If it fails (disk full, permissions, a missing directory) the detached first launch still starts, but the daemon has no marker to service, so there is no second run, and no log line says the marker was not written. To do: log the failure through state.log_line in the same place (the hook must still never raise), with one test that makes the write fail and asserts the log line. Smallest change; no retry logic is to be added.

## Approval log

- 2026-10-10T16:33:52+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
