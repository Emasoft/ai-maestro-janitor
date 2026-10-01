---
trdd-id: RQMJFJGR
title: C41 — autorecall passes scope dirs
column: blocked
status: tasked
created: 2026-10-01T19:45:22+0200
updated: 2026-10-01T19:48:19+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:22+0200
blocked-by: [QXG8SRVD, ZYX8B2RA]
pre-block-column: todo
blocker-probe: [trddgrep, why, RQMJFJGR]
blocker-holds-if: not-match:READY
---

# C41 — autorecall passes scope dirs

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C41, wave W4.

Writes (exclusive): scripts/hooks/on-prompt-submit-autorecall.py (C25's file, so runs after C25)
Task: Autorecall passes the 3 scope dirs instead of a file list, if C1D shows that's faster
Verify: Same as C40
Depends on: C25, C40
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:22+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:45+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on QXG8SRVD, ZYX8B2RA per DSN035UN wave order
