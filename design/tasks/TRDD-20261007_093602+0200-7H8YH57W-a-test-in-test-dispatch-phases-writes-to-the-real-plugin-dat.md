---
trdd-id: 7H8YH57W
title: A test in test_dispatch_phases writes to the real plugin data usage-probe folder
column: todo
status: tasked
created: 2026-10-07T09:36:02+0200
updated: 2026-10-07T09:36:02+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T09:36:02+0200
---

# A test in test_dispatch_phases writes to the real plugin data usage-probe folder

Observed 2026-10-07 during batch B8: running tests/test_dispatch_phases.py printed "[plugin-data] CHANGED ... usage-probe/*.json", so a test touches the real plugin DATA dir. Find the test, isolate it to a tmp dir, add a guard.

## Approval log

- 2026-10-07T09:36:02+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
