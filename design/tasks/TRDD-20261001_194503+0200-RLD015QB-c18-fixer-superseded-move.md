---
trdd-id: RLD015QB
title: C18 — fixer superseded_move
column: ai_review
status: tasked
created: 2026-10-01T19:45:03+0200
updated: 2026-10-04T13:25:53+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:03+0200
blocked-by: []
pre-block-column: 
blocker-probe: [trddgrep, why, RLD015QB]
blocker-holds-if: not-match:READY
implementation-commits: [9fb13752, 9254214e]
---

# C18 — fixer superseded_move

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C18, wave W1.

Writes (exclusive): src/fixers/superseded_move.rs
Task: SAFE fixer: superseded move
Verify: Each test: (a) a before/after literal; (b) a lossless assert (prefix-preserving, unquote = original, set unchanged, block multiset byte-equal, only the comment removed); (c) oracle: lint_page_text(fixed) lacks the code
Depends on: C02
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:03+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:45:55+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 622ROA5F per DSN035UN wave order
- 2026-10-04T13:10:59+0200 — column → todo by main-agent@ai-maestro-janitor. blocker 622ROA5F is complete and archived Cleared blocked-by (--clear-blocker override).
- 2026-10-04T13:11:11+0200 — column → testing by main-agent@ai-maestro-janitor. fixer implemented in 9fb13752, unit-tested, awaiting review
- 2026-10-04T13:25:11+0200 — column → ai_review by main-agent@ai-maestro-janitor. implemented and unit-tested, not wired into lint; testing overstated it
