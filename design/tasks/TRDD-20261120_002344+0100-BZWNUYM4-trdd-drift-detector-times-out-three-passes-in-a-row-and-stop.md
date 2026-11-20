---
trdd-id: BZWNUYM4
title: trdd-drift detector times out three passes in a row and stops completing
column: todo
status: tasked
created: 2026-11-20T00:23:44+0100
updated: 2026-11-20T00:23:44+0100
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
approval-datetime: 2026-11-20T00:23:44+0100
---

# trdd-drift detector times out three passes in a row and stops completing

2026-11-20 heartbeat stdout (verbatim): '[findings] HIGH DETECTOR-FAIL (trdd-drift): detector trdd-drift failed 3 passes in a row (error:timeout); not completing'. Hypothesis, not measured: the board has grown (design/tasks plus archived/ plus LOCAL roots) and the detector no longer finishes inside its budget. While it times out, card drift (stale dev/testing cards, blocked-by checks, unblock-when) is not reported; only the DETECTOR-FAIL finding surfaces. Needed: measure one pass (wall time and which phase), then bound it (incremental scan by mtime, or a per-pass card cap with a cursor) so every card is still covered within a few passes; a test with a large synthetic corpus in tmp_path that fails on the unbounded version.

## Approval log

- 2026-11-20T00:23:44+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
