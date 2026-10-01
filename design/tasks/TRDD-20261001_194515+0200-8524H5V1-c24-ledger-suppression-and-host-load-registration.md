---
trdd-id: 8524H5V1
title: C24 — ledger suppression and host-load registration
column: blocked
status: tasked
created: 2026-10-01T19:45:15+0200
updated: 2026-10-01T19:46:12+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:15+0200
blocked-by: [U2VUXGBP, UDE86OSZ]
pre-block-column: todo
---

# C24 — ledger suppression and host-load registration

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C24, wave W2.

Writes (exclusive): scripts/lib/findings_ledger.py, scripts/dispatch.py
Task: Route ledger records and drift lines through is_suppressed; register host-load.py; map system-daemon-runaway to HOST-002
Verify: One heartbeat with ignore=["HOST"] in .janitor.toml prints no HOST line; without it the line prints with its code
Depends on: C1A, C1C
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:15+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:12+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on U2VUXGBP, UDE86OSZ per DSN035UN wave order
