---
trdd-id: QL2E90XY
title: Test runs may write to the real plugin-data global-state dir, four write-guard notices unexplained
column: todo
status: tasked
created: 2026-11-20T00:13:12+0100
updated: 2026-11-20T00:13:12+0100
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
approval-datetime: 2026-11-20T00:13:12+0100
---

# Test runs may write to the real plugin-data global-state dir, four write-guard notices unexplained

2026-11-20, from the B607 lane T2 report (reports_dev/cheap-worker/20261119_235635+0100-b607-T2.md): single-file pytest runs of tests/test_stale_stash.py (1 notice) and tests/test_trdd_state_reconciliation.py (3 notices) produced real-state write-guard mutation notices under the real plugin-data global-state dir. The guard attributed them to a live janitor actor (daemon pid 7251); daemon.log memory-guard ticks write the same snapshot at the same times, but a test write is not excluded. Needed: rerun each file with the daemon's writes distinguishable (compare the mutated paths and mtimes against daemon.log ticks, or run with the daemon paused), and either prove the daemon wrote them or fix the leaking test. Also: pre-commit runs fail with REAL-STATE WRITE GUARD FAILED whenever another agent edits a tracked source file mid-run (seen 2026-11-20 on scripts/lib/usage_probe.py); that is a correct detection but blocks commits during parallel work.

## Approval log

- 2026-11-20T00:13:12+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
