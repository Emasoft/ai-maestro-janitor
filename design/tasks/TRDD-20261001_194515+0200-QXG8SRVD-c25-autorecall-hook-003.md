---
trdd-id: QXG8SRVD
title: C25 — autorecall HOOK-003
column: blocked
status: tasked
created: 2026-10-01T19:45:15+0200
updated: 2026-10-01T19:48:13+0200
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
blocked-by: [B9YPSF02]
pre-block-column: todo
blocker-probe: [trddgrep, why, QXG8SRVD]
blocker-holds-if: not-match:READY
---

# C25 — autorecall HOOK-003

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C25, wave W2.

Writes (exclusive): scripts/hooks/on-prompt-submit-autorecall.py, hooks/hooks.json
Task: Record HOOK-003 when the internal recall limit trips (F13); add the hook-timing wrapper's config if C1B needs it
Verify: A forced 0.01 s internal limit gives one HOOK-003 record
Depends on: C1B
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:15+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:13+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on B9YPSF02 per DSN035UN wave order
