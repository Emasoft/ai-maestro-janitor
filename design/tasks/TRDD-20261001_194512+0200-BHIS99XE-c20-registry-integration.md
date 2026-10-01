---
trdd-id: BHIS99XE
title: C20 — registry integration
column: blocked
status: tasked
created: 2026-10-01T19:45:12+0200
updated: 2026-10-01T19:57:57+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:12+0200
blocked-by: [2UAEQQ4A]
pre-block-column: todo
blocker-probe: [trddgrep, why, BHIS99XE]
blocker-holds-if: not-match:READY
---

# C20 — registry integration

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C20, wave W2.

Writes (exclusive): src/memory.rs
Task: Registry integration: push-site severity comes from rule(); the floors and grandfathered lists are derived from gate_floor; test every_emitted_code_is_registered; fix the F2/F16 comments
Verify: Rust gate passes; lint --no-fix output on the PROJECT memory is byte-identical before vs after, except D1's two codes
Depends on: C10
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:12+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:08+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 2UAEQQ4A per DSN035UN wave order
- 2026-10-01 — FACT from C01 (supersedes plan F1 "37 literals"): memory.rs has 34 `code: "` literals; six memgrep codes are emitted without one (atom-no-ocd, atom-no-lmd, atom-bad-ocd, atom-bad-lmd, publish-globally-not-symlinked, publish-globally-conflict). every_emitted_code_is_registered must therefore NOT rely on a `code: "` source scan alone: find how those six are constructed (tldr/jgrep) and cover them, e.g. by asserting the registry against the codes produced by linting a fixture corpus that triggers every rule, or by scanning every string literal passed into a Violation.
- 2026-10-01 — STYLE (wave-1 review finding 7): C02 placed the new mod lines after const MD_EXTS in main.rs instead of inside the existing mod block; move them into the block when this card touches main.rs.
