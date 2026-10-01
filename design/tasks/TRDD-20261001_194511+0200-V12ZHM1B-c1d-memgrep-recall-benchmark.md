---
trdd-id: V12ZHM1B
title: C1D — memgrep recall benchmark
column: dev
status: tasked
created: 2026-10-01T19:45:11+0200
updated: 2026-10-01T19:50:11+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:11+0200
blocked-by: []
pre-block-column: 
blocker-probe: [trddgrep, why, V12ZHM1B]
blocker-holds-if: not-match:READY
---

# C1D — memgrep recall benchmark

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C1D, wave W1.

Writes (exclusive): scripts_dev/memgrep_bench.py, report under reports/memgrep-perf/
Task: Benchmark on an idle host (U9): recall over 369 files, recall over 3 dirs, lint over 3 scopes, cold start; plus a sample/dtruss profile of the 5 s recall to explain the gap between 0.34 s CPU and 5 s wall
Verify: The report names the dominant wait (index open, per-file stat, lock or load), with numbers
Depends on: C02
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:11+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:05+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 622ROA5F per DSN035UN wave order
- 2026-10-01T19:50:11+0200 — column → dev by main-agent@ai-maestro-janitor. C1D is a Python/benchmark card with no dependency on the C02 Rust scaffold; blocker was over-broad (minting rule 'W1 depends on C02'); dispatched 2026-10-01 Cleared blocked-by (--clear-blocker override).
