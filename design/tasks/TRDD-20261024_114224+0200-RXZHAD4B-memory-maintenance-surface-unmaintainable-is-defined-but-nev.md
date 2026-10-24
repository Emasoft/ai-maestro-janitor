---
trdd-id: RXZHAD4B
title: memory-maintenance _surface_unmaintainable is defined but never called
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

# memory-maintenance _surface_unmaintainable is defined but never called

Found by the TRDD-F3LVCQ39 census. A grep of scripts/ finds only the definition at scripts/detectors/memory-maintenance.py:546 and no caller, so the memory-unmaintainable condition it would surface never reaches anyone. ACCEPTANCE: find whether the call was dropped by a refactor (git log -S), then either restore the call with a test that the condition surfaces, or delete the function and its seen-file handling.

## Approval log

- 2026-10-24T11:42:24+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
