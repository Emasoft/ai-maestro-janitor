---
trdd-id: b3eae1cd-97c3-4f5b-b26f-aa6c72f81af9
title: memory-librarian — gate conflict/aggregation on subject-entity + cohesion, not keyword overlap
column: todo
created: 2026-06-14T17:30:03+0200
updated: 2026-06-18T19:35:24+0200
current-owner: ai-maestro-janitor
task-type: refactor
priority: 6
severity: LOW
effort: M
labels: [memory-librarian, heuristics, false-positive]
release-via: publish
test-requirements: [unit]
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/35"]
---

# memory-librarian — gate conflict/aggregation on subject-entity + cohesion, not keyword overlap

## Problem (issue #35)

The `memory-librarian` detector's `conflict` and `aggregation` candidate
proposals cluster on shared `description`/`tags` **tokens**. On a small,
domain-clustered corpus a shared domain term (e.g. "cpv", "code", "plugin",
"publish", "memory") dominates, producing false candidates:

- A 5-note **aggregation** of genuinely distinct topics that merely share the
  word "cpv" — merging would violate one-element-one-page.
- A **conflict** between two *complementary* notes (one even cites the other's
  discipline) — topic overlap, not contradiction.

This recurs fleet-wide: every plugin's corpus fills with shared domain keywords,
so on small/early corpora the overlap dominates and trains agents to ignore the
librarian's proposals — eroding trust in a useful tool. Tightening note
`description`s to dodge it would hurt symptom-indexed recall, so the fix belongs
in the detector.

## Direction (reporter-suggested, agreed)

- **conflict**: require a detected **contradiction** (opposing / negated claims
  about the same subject), or at minimum a shared **subject entity** — not mere
  shared tokens. Two compatible notes about the same domain are not a conflict.
- **aggregation**: require same-element/topic similarity above a higher bar than
  single-keyword overlap (a minimum cluster-cohesion threshold), so a domain
  term spanning distinct notes does not collapse them.

## Why deferred (not a quick patch)

Tightening the clustering risks regressing the detector's **recall** of real
merge candidates. Before shipping, build a small labeled corpus — true-positive
merges (must still be proposed) plus the issue-#35 false-positive clusters as
negatives — and validate the new thresholds against it. The exact cohesion
metric and contradiction signal are a design choice to settle during the work.

## Acceptance criteria

- The issue-#35 example clusters (5-note "cpv" aggregation; the complementary
  "conflict" pair) no longer produce candidates.
- A genuine same-element duplicate pair IS still proposed for aggregation.
- A genuinely contradictory pair IS still proposed as a conflict.
- No regression in the existing `test_memory_librarian.py` candidate tests.

## STATE

Promoted backburner → `todo`. This is the **NPT** (necessary prerequisite) for the
wikimem-editor executors TRDD-c5da00c0 (SPLIT), TRDD-31168858 (MERGE), and
TRDD-88bdf651 (CONFLICT) — every executor consumes the librarian's candidate pool,
so a noisy pool wastes the editorial agents' tokens. Solo-actionable (janitor's own
detector). The conflict/aggregation clustering lives in
`scripts/detectors/memory-librarian.py`; tests in `tests/test_memory_librarian.py`.
Issue #35 carries the reporter's concrete false-positive examples (seed the negative
set from them).
