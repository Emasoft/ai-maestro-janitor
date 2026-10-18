---
trdd-id: BEA87JS1
title: Token-spike advisory renders output ~0k and still recommends compaction
column: todo
status: tasked
created: 2026-10-18T08:58:49+0200
updated: 2026-10-18T08:58:49+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-18T08:58:49+0200
parent-trdd: 9WPZE2NQ
---

# Token-spike advisory renders output ~0k and still recommends compaction

janitor#342 item 5c, CONFIRMED 2026-10-18 by TRDD-9WPZE2NQ (reports/board/20261018_085812+0200-9wpze2nq-342-items-3-5.md). scripts/hooks/pre-tool-token-budget.py _bucket_tokens (line 230) floors every count to 10k for cache-stable text (TRDD-YRPUSIFY), so any count under 10k renders '~0k'. The advisory threshold is baseline-relative (scripts/lib/token_meter.py about 803-816: max(p95, median+3*1.4826*MAD, 4*median)), so on a low-output session it fires below 10k and prints 'Token spike: this turn output ~0k ... or compact' (message built near line 440). Reproduced by the worker with history [800,1000,900,1100,1000,950,1050,1200] and output 6000. Overlaps #246, whose fix made the bar baseline-relative but left the bucket floor. Fix direction: finer buckets below 10k that stay byte-identical within a band, and/or no compact recommendation below a fixed floor. Acceptance: a test with that history asserts the advisory text has no '~0k' and no compact advice, fails before and passes after; the bucket-stability tests still pass; full gate green.

## Approval log

- 2026-10-18T08:58:49+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
