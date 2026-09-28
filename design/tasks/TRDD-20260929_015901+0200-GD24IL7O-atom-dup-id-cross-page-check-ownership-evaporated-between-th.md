---
trdd-id: GD24IL7O
title: atom-dup-id cross-page check — ownership evaporated between the step-2 floor table and the batch layer
column: todo
status: tasked
created: 2026-09-29T01:59:01+0200
updated: 2026-09-29T01:59:10+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-09-29T01:59:01+0200
---

# atom-dup-id cross-page check — ownership evaporated between the step-2 floor table and the batch layer

Found by BOTH wave-2 review forks (2026-09-29). Step-2's landing record excluded atom-dup-id and link-one-sided from the per-page floor table because they are cross-page and 'step 3's prepare_batch owns them'. The batch layer (prepare_batch_gated, commit 190573d8) landed owning NEITHER: link-one-sided is honestly deferred to A2 step 6, but atom-dup-id appears NOWHERE — no refusal, no test, no card record naming an owner. Worse, id_inventory's entry().or_insert actively collapses a duplicate id across two batch pages into one entry, so a write leaving the same atom id on two pages passes DROP (union still has it), passes REUSE (same fingerprint), and passes the per-page floors (the code is excluded from the table): the gate certifies a malformed cross-page state with no detector in the pipeline — the exact citation-ambiguity class the id rule exists to prevent. This is the evaporation class the card's A2-close rule warns about (prose does not participate in close-time gating). Fix (two parts): (a) batch-INTERNAL duplicate check — after building the proposed inventories, refuse any id minted on two different pages of the same batch; (b) the cross-BATCH boundary (an id minted on a page inside the batch that already exists on a page OUTSIDE it) needs a scope-wide inventory read or an explicit owner decision — record it as a STRUCTURED item on TRDD-XI10BA5D before A2 closes, never prose in an Implementation tail. Test: a two-page batch where page B mints an id that already exists on page A refuses naming both pages; a batch where the id moves A to B (dup resolved by the move) passes.

## Approval log

- 2026-09-29T01:59:01+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
