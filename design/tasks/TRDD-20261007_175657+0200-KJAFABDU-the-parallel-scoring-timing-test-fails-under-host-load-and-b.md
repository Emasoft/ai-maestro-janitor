---
trdd-id: KJAFABDU
title: The parallel-scoring timing test fails under host load and blocks pushes
column: todo
status: tasked
created: 2026-10-07T17:56:57+0200
updated: 2026-10-07T17:56:57+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T17:56:57+0200
---

# The parallel-scoring timing test fails under host load and blocks pushes

tests/test_jev_compaction.py::test_score_items_parallel_is_faster_than_serial asserts parallel < serial/2 on wall clock. At host load about 127 it measured parallel 1.01 s vs serial 1.05 s and the push hook refused the 3.8.8 push. score_items always uses ThreadPoolExecutor(max_workers) (read 2026-10-07; no serial fallback), so the failure is CPU starvation, not a code path. Fix: assert overlap instead of speed, e.g. count requests in flight at once and require at least 2, or record each batch's sleep interval and require two to overlap.

## Approval log

- 2026-10-07T17:56:57+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
