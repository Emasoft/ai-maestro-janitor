---
trdd-id: B26WBXDW
title: MODEL-FALLBACK findings reach a new session despite the control-plane exclusion
column: todo
status: tasked
created: 2026-10-24T11:42:23+0200
updated: 2026-10-24T11:42:23+0200
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
approval-datetime: 2026-10-24T11:42:23+0200
---

# MODEL-FALLBACK findings reach a new session despite the control-plane exclusion

Found by the TRDD-F3LVCQ39 census. dispatch.py:889 (_exclude_control_plane_output) blanks model-fallback's stdout because its output must not reach an agent. But model-fallback.py:323 also calls findings_ledger.record (sev HIGH when the switch is not confirmed), and surface_block (findings_ledger.py:579) filters only NEVER_SURFACE_CODES, which holds only WINDOW-BURN (findings_ledger.py:95). So a MODEL-FALLBACK row can be injected at SessionStart (read in code). Not verified: that the ledger record() writes here is the one SessionStart reads for this project. ACCEPTANCE: decide whether MODEL-FALLBACK belongs in NEVER_SURFACE_CODES (or the record is dropped), apply it, and add a test that a MODEL-FALLBACK row never appears in surface_block output.

## Approval log

- 2026-10-24T11:42:23+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
