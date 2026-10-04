---
trdd-id: 3HLI7DMK
title: C21 — labels and lint flags
column: dev
status: tasked
created: 2026-10-01T19:45:12+0200
updated: 2026-10-05T01:56:39+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:12+0200
blocked-by: []
pre-block-column: 
blocker-probe: [trddgrep, why, 3HLI7DMK]
blocker-holds-if: not-match:READY
---

# C21 — labels and lint flags

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C21, wave W2.

Writes (exclusive): src/memory.rs, scripts/memgrep/tests/cli.rs
Task: Labels ' (FAMILY-NNN · safe-fix)' before the anchor; flags --select, --extend-select, --ignore, --statistics, --exit-zero, --output-format json, --config, --isolated, wired to C11 and C12; emit WMSUP-*
Verify: CLI tests per flag; pytest feeds a labelled line to _LINE_RE and the 4 precheck regexes; wikimem-syntax.py summary still prints
Depends on: C20, C11, C12
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:12+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:09+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on BHIS99XE, OWGEOJ0D, 7SMPCPNT per DSN035UN wave order
- 2026-10-01 — DESIGN NOTE (review finding 4): print the safe-fix label on a finding only when the registered fixer would actually change that page (e.g. atom-unquoted-desc over 200 chars has no fix) — a label that promises a fix the engine will not make is a lie.
- 2026-10-05T01:56:08+0200 — column → todo by main-agent@ai-maestro-janitor. its only open blocker C20 (BHIS99XE) was completed on 2026-10-05; OWGEOJ0D and 7SMPCPNT were already complete Cleared blocked-by (--clear-blocker override).
- 2026-10-05T01:56:39+0200 — column → dev by main-agent@ai-maestro-janitor. a worker starts the implementation on 2026-10-05 per plan DSN035UN card C21

## STATE

2026-10-05: blocked-by trimmed to BHIS99XE (C20, in ai_review). OWGEOJ0D (C11) and 7SMPCPNT (C12) are complete and archived, so listing them raised GRAPH-DANGLING-BLOCKER. Note for this card: the C19 unused-noqa fixer tests carry a has_code assert that cannot fail until this card makes lint emit unused-noqa; re-run them then (see archived TRDD-RUJQ7WSX).
2026-10-05 later: column dev; C20 (BHIS99XE) is complete and archived, blocked-by is empty. One worker is implementing the card from the DSN035UN plan text. NEXT ACTION: when the worker reports, the main agent reads the full diff, runs cargo test and clippy on a still tree with exit codes read directly, runs the pytest files named in Verify, then re-runs the C19 fixer tests with a real has_code oracle.
