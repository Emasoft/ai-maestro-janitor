---
trdd-id: ZYX8B2RA
title: C40 — fix dominant recall wait
column: blocked
status: tasked
created: 2026-10-01T19:45:21+0200
updated: 2026-10-01T19:48:18+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:21+0200
blocked-by: [V12ZHM1B]
pre-block-column: todo
blocker-probe: [trddgrep, why, ZYX8B2RA]
blocker-holds-if: not-match:READY
---

# C40 — fix dominant recall wait

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C40, wave W4.

Writes (exclusive): set in the card from C1D's report (depends on the cause)
Task: Fix the dominant wait C1D names. Candidate fixes: open the index once, avoid per-file stats when --use-index is given, or pass scope dirs instead of 369 file paths.
Verify: Rerun C1D's benchmark on an idle host; recall over 3 scopes takes under 1 s, and an autorecall prompt produces no HOOK-003
Depends on: C1D
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:21+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:43+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on V12ZHM1B per DSN035UN wave order
