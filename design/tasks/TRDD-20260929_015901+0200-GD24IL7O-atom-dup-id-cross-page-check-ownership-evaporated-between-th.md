---
trdd-id: GD24IL7O
title: atom-dup-id cross-page check — ownership evaporated between the step-2 floor table and the batch layer
column: testing
status: tasked
created: 2026-09-29T01:59:01+0200
updated: 2026-09-30T00:19:44+0200
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
- 2026-09-29T09:11:14+0200 — column → todo. content verification (XI10BA5D check-box): part (a) landed e559e25c, part (b) + 3 landing-review obligations open, no active worker — WORK-column claim untrue; todo is the honest state

## Implementation

2026-09-29 PART (a) LANDED (commit e559e25c, lean-worker, main-verified): refuse_cross_page_duplicate_ids over the PROPOSED batch — id on 2 pages of the batch refuses; an id ALREADY duplicated on disk that the write merely preserves passes (freezing an inherited dup would make it unrepairable); cross-BATCH boundary stays the structured item on XI10BA5D (part b). 2 new tests, 338 unit + 171 cli green (main ran), no-leak intact. Moving to testing.
2026-09-29 landing review (HOLDS, 3 discharges before terminal): (1) CURE — the inherited-preserve rule licenses SPREAD: 1→2 passes but 1→2 is not preservation, it mints a new dup instance from clean state; refuse count-growth on an inherited id (one test). (2) The refusal message/doc comment must carry the batch-internal-only qualifier (comprehension). (3) LOW: the mypy fix rode the VIFQ1LKI commit (cosmetic). These are next-touch obligations on this card, not new cards — the card cannot go terminal without them.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-29

2026-09-29: this card now gates TRDD-XI10BA5D's close — XI10BA5D's eht lists it (correction round 2026-09-29). Directional signal added per the close-out review (the gate was one-directional until now). XI10BA5D's verification check-box requires reading this card's content and truing the column; step 6's link check resolves names not ids so the id-collapse defect does not directly corrupt it, but both run inside one prepare whose inventory is the contested object.
True state (2026-09-29, added per the heading-fix review): part (a) LANDED e559e25c per the Implementation section below (landing review HOLDS, 3 next-touch obligations recorded there — spread-rule CURE, batch-internal-only qualifier, cosmetic mypy rider); part (b) cross-batch boundary OPEN; card in testing; the coordination note below concerns XI10BA5D gating only.
2026-09-30 dispatch: spread-rule CURE test (inherited_dup_spread_to_a_second_page_refuses) in flight — lean-worker, test-only, filter at pre_write.rs:226 verified already refusing 1→2 growth (byte-identical to e559e25c); obligations 2 (batch-internal qualifier) rides the same test's message assertion; obligation 3 (mypy rider) is record-only, discharged at commit time. Card moved todo→dev (WORK column now true).
2026-09-30 dispatch-review (fork, HOLDS-with-findings) + landing verification: the spread test LANDED and was independently verified (main ran it; old inventory confirmed non-vacuous — the atom is on disk page A before the batch, so old=1→2 refuses, the review's exact CURE case). Review fixes applied: (1) test renamed inherited_dup_spread_to_a_second_page_refuses → spread_from_one_page_to_two_refuses (the old name mislabeled 1→2 as 'inherited dup'); the doc comment now names the unpinned old=2 pair (2→3 growth refuse / preserve-pass) as a recorded test debt — the filter's same max-floor arithmetic, one future test when touched. (2) Record correction: obligation 2 was ALREADY discharged by e559e25c itself (message qualifier + doc comment); the new test only PINS it against regression — the earlier dispatch line's 'rides the same test's assertion' overstated. (3) Obligation 3 (mypy rider, VIFQ1LKI cosmetic) is record-only and is discharged BY THIS LINE's record + the commit message at commit time — the committer is this session (parent), not the worker. (4) Post-worker column hygiene: dev→testing in the same turn as the worker's completion report. 'byte-identical to e559e25c' method: whole-file diff attributed the 419-line delta to later commits plus the filter line's exact match.
