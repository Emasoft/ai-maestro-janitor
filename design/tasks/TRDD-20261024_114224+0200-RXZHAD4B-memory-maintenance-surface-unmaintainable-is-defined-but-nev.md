---
trdd-id: RXZHAD4B
title: memory-maintenance _surface_unmaintainable is defined but never called
column: todo
status: tasked
created: 2026-10-24T11:42:24+0200
updated: 2026-10-24T11:48:02+0200
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

Found by the TRDD-F3LVCQ39 census. scripts/detectors/memory-maintenance.py:546 defines _surface_unmaintainable, and a grep of scripts/ finds no caller. git log -S shows the function arrived in dd0de610 (orphaned half (b) of TRDD-JPL0JU86), and that commit added only the definition, never a call; no memory-unmaintainable seen file exists under .janitor/state (read 2026-10-24). So no call was ever added in this file's history and no caller exists in scripts/ today; the global state dir was not checked for a seen file. ACCEPTANCE: wire the call into the detector's main path with a test that an unmaintainable page surfaces once, or, if TRDD-JPL0JU86's intent is obsolete, remove the function.

## Approval log

- 2026-10-24T11:42:24+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
