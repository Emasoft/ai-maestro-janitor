---
trdd-id: V5FP4506
title: Windows desktop notification backend for notify.py
column: backburner
status: tasked
created: 2026-10-21T20:59:33+0200
updated: 2026-10-21T20:59:33+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-21T20:59:33+0200
---

# Windows desktop notification backend for notify.py

Split from TRDD-1J9B7MWO (advisor + review 2026-10-21). USER ruling: launch a system notification depending on the platform. notify.py covers only macOS (osascript) and Linux (notify-send). Add a Windows backend (PowerShell toast under PowerShell's own AppUserModelID) with a test of the built command line; display on Windows stays unverified until run there. EHT of TRDD-1J9B7MWO: the parent cannot complete while Windows users get no notification.

## Approval log

- 2026-10-21T20:59:33+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
