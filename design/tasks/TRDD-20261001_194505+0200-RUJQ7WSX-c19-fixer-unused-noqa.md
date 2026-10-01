---
trdd-id: RUJQ7WSX
title: C19 — fixer unused_noqa
column: blocked
status: tasked
created: 2026-10-01T19:45:05+0200
updated: 2026-10-01T19:45:57+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:05+0200
blocked-by: [622ROA5F]
pre-block-column: todo
---

# C19 — fixer unused_noqa

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C19, wave W1.

Writes (exclusive): src/fixers/unused_noqa.rs
Task: SAFE fixer: unused noqa
Verify: Each test: (a) a before/after literal; (b) a lossless assert (prefix-preserving, unquote = original, set unchanged, block multiset byte-equal, only the comment removed); (c) oracle: lint_page_text(fixed) lacks the code
Depends on: C02
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:05+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:45:57+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 622ROA5F per DSN035UN wave order
