---
trdd-id: EMZUVIBK
title: C34 — memgrep perf budget
column: todo
status: tasked
created: 2026-10-01T19:45:21+0200
updated: 2026-10-06T20:03:31+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:21+0200
blocked-by: []
pre-block-column: 
blocker-probe: [trddgrep, why, EMZUVIBK]
blocker-holds-if: not-match:READY
---

# C34 — memgrep perf budget

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C34, wave W3.

Writes (exclusive): src/perf_budget.rs, scripts/memgrep/tests/cli.rs (perf section only)
Task: memgrep times its own recall and lint against [perf] budgets; emits MGPERF-001/002 on stderr/JSON
Verify: A CLI test with a 1 ms budget gives an MGPERF-001 line
Depends on: C21
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:21+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:41+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 3HLI7DMK per DSN035UN wave order
- 2026-10-06T20:03:31+0200 — column → todo by main-agent@ai-maestro-janitor. only blocker 3HLI7DMK complete Cleared blocked-by (--clear-blocker override).
