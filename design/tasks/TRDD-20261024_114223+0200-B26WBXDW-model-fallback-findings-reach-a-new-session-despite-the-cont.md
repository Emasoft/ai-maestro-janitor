---
trdd-id: B26WBXDW
title: MODEL-FALLBACK findings reach a new session despite the control-plane exclusion
column: todo
status: tasked
created: 2026-10-24T11:42:23+0200
updated: 2026-10-24T11:48:04+0200
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

Found by the TRDD-F3LVCQ39 census. The owner's ruling recorded verbatim in TRDD-1J9B7MWO (USER 2026-10-21: warnings about account exhaustion should not be surfaced to the agents; that card is still in todo, its implementation pending) covers this detector's account and rotation lines; and dispatch.py:889 (_exclude_control_plane_output) blanks model-fallback's stdout accordingly. But model-fallback.py:323 also calls findings_ledger.record (sev HIGH when the switch is not confirmed), and surface_block (findings_ledger.py:579) filters only NEVER_SURFACE_CODES, which holds only WINDOW-BURN (findings_ledger.py:95). So a MODEL-FALLBACK row can be injected at SessionStart. Read in code: the record call, NEVER_SURFACE_CODES and surface_block's body. Not verified: _unread_snapshot (which feeds surface_block) was only partly read, and that the ledger written here is the one SessionStart reads. ACCEPTANCE: per TRDD-1J9B7MWO, add MODEL-FALLBACK to NEVER_SURFACE_CODES (or stop recording it), with a test that a MODEL-FALLBACK row never appears in surface_block output.

## Approval log

- 2026-10-24T11:42:23+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
