---
trdd-id: IFILAUV5
title: batch atomicity contract for the gated batch verbs — ratify per-page commits or build true batch atomicity
column: todo
status: tasked
created: 2026-09-29T08:51:23+0200
updated: 2026-09-29T08:51:23+0200
current-owner: user
created-by: user
task-type: feature
min-approval-requirement: none
assignee: user
mandate: true
mandated-by: none
approved: true
approval-judge: user
approval-datetime: 2026-09-29T08:51:23+0200
---

# batch atomicity contract for the gated batch verbs — ratify per-page commits or build true batch atomicity

Derived from TRDD-XI10BA5D A2-CLOSE checklist (eht — XI10BA5D cannot reach complete until this card is terminal). The wave-2 gate (prepare_batch_gated, commit 190573d8) validates the whole batch BEFORE any commit, then each caller commits its pages in order through the per-page gate. An abort mid-commit leaves SOME pages committed: the corpus stays consistent-though-incomplete (per-page writes are individually atomic; no torn page), never corrupted — the deferral was judged sound 2026-09-29. Worker-recorded partial-write windows, quoted verbatim from the wave-2 landing record: 'merge (PARTIAL MERGE), split (PARTIAL SPLIT), migrate (B-then-A duplicate-not-loss), reference-* (idempotent self-heal)'. DECISION OWED (owner): ratify per-page gating as the CONTRACT (batch verbs document PARTIAL recovery; this card closes accepted-ceiling), or build true batch atomicity (staged batch write / two-phase commit) in memgrep. Interim guarantee holds either way: a refused batch commits nothing; only a mid-commit crash or failure can leave the incomplete state, and every verb's PARTIAL recovery path survives unchanged.

## Approval log

- 2026-09-29T08:51:23+0200 — MANDATE issued by user (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
