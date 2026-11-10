---
trdd-id: Q3SR1ZK2
title: switch jev scoring to llm-ext classify — keep compaction pipeline shape
column: todo
status: tasked
created: 2026-11-10T19:04:51+0100
updated: 2026-11-10T19:04:51+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-10T19:04:51+0100
---

# switch jev scoring to llm-ext classify — keep compaction pipeline shape

Owner directive 2026-11-10: 'if you use jev directly somewhere, switch to use it through llm-ext classifiers commands.' The ONE direct Jev use is jev_compact.py:578 calling jc.score_items(items, digest, client) where client = make_client() (jevctx.openrouter). score_items (jev_compaction.py:1049) batches items and calls client.ask(state, questions) per batch (_score_batch:915), getting back NoulAnswer relevance scores. This IS a classification task — relevance ranking of transcript items. ADVISOR VERDICT (fable-advisor, 2026-11-10): do NOT swap primary/fallback in run_compact_with_fallback — that changes the output shape (pointers, inject rendering). Instead replace the SCORING call: route score_items through llm-ext classify rank or classify decide, keeping the compaction pipeline (pointers, compose, inject-out) intact. The change: (1) a new scoring adapter that calls llm-ext classify with the same digest+items+relevance question, returning the same Scores dict shape; (2) jev_compact.py uses the adapter instead of make_client()+jc.score_items; (3) jev_compact.py stays as fallback. RISKS: llm-ext classify returns text, not structured NoulAnswer — the adapter must parse the response into the Scores dict. The batching/splitting/resilience in score_items is Jev-specific — the adapter may need its own batching. Tests in tests/test_jev_boundary.py and compaction tests assume Jev as the scoring provider.

## Approval log

- 2026-11-10T19:04:51+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
