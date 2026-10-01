---
trdd-id: OLNPXGBC
title: C31 — shrink repair skill
column: blocked
status: tasked
created: 2026-10-01T19:45:18+0200
updated: 2026-10-01T19:48:15+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:18+0200
blocked-by: [JD2QR5SQ]
pre-block-column: todo
blocker-probe: [trddgrep, why, OLNPXGBC]
blocker-holds-if: not-match:READY
---

# C31 — shrink repair skill

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C31, wave W3.

Writes (exclusive): skills/janitor-memory-repair/SKILL.md (+ references)
Task: Replace the mechanical checklist bullets with the fixer instruction; offer the owner the injection-guard restore (IKZROIE5 Q5) as an option
Verify: The token-cap test passes; the before/after count is recorded
Depends on: C22
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:18+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:19+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on JD2QR5SQ per DSN035UN wave order
