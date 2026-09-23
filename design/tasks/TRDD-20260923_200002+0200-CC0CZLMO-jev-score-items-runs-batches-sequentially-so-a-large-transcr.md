---
trdd-id: CC0CZLMO
title: Jev score_items runs batches sequentially so a large transcript exceeds both compaction lane timeouts
column: testing
created: 2026-09-23T20:00:02+0200
updated: 2026-09-23T21:10:50+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: bugfix
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-23T20:00:02+0200
parent-trdd: RAEGS1D5
---

# Jev score_items runs batches sequentially so a large transcript exceeds both compaction lane timeouts

A 49 MB real transcript (7075 items) took 168 s in jev_compact.py compact on 2026-09-23 (HEAD tree), over the sync 60 s and the old detached 120 s timeouts; a 4.7 MB one took 10 s. score_items loops over batches sequentially (a plain for loop; the run_compact docstring's 'six parallel batches' is stale). Fix: score batches concurrently within OpenRouter's rate limits (httpx is available in jev_compact.py), keep deterministic ordering, and re-measure both transcripts. Acceptance: 49 MB under 60 s, or the measured time recorded with the chosen concurrency; the 4.7 MB result unchanged in content. Coordinate with the reference-adoption rework (TRDD-RAEGS1D5 gap analysis): if the reference pipeline replaces score_items, fold this into that card.

## Approval log

- 2026-09-23T20:00:02+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-23T21:10:50+0200 — column → testing. code landed and committed 2026-09-23 with tests; awaiting the real-transcript compaction on the final tree and the release
