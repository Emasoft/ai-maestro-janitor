---
trdd-id: 4DP942BO
title: branch_protection_apply output reaches the heartbeat unfiltered
column: todo
status: tasked
created: 2026-10-24T11:42:24+0200
updated: 2026-10-24T11:42:24+0200
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
approval-datetime: 2026-10-24T11:42:24+0200
---

# branch_protection_apply output reaches the heartbeat unfiltered

Found by the TRDD-F3LVCQ39 census. dispatch.py:3574-3576 runs scripts/guard/branch_protection_apply.py with capture_output=False, so the child inherits the dispatcher stdout: whatever it prints reaches the heartbeat output with no defang, quiet filter or daily dedupe (read in code). A worker reported four print sites in the script (not read here). ACCEPTANCE: capture its output and route it through the same pipeline as detector output, or prove each print is safe to pass raw, with a test.

## Approval log

- 2026-10-24T11:42:24+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
