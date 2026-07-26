---
trdd-id: YBOZW3ES
title: A page result's locator is an absolute path — the single most expensive field recall prints
column: todo
created: 2026-07-26T20:18:53+0200
updated: 2026-07-26T20:18:53+0200
current-owner: 2f5bc976
task-type: refactor
approval-tier: 0
scope: project
release-via: publish
impacts: [memgrep, wikimem]
relevant-rules: []
implementation-commits: []
---

# A page result's locator is an absolute path

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-26

- **Component state — MEASURED, NOT STARTED.** No code written. The measurement below is the
  expensive part and is done; do not re-derive it.
- **NEXT ACTION:** decide the locator identity (see "The open decision"), then implement in
  `memory.rs`: thread the page `name:` into `CandidateMeta`/`RecallRanked` on BOTH gather paths
  (walk AND index — they must rank and print identically), print it as the lean-layer page
  locator, and add the exact page-name hop beside `atom_id_query`/`recall_one_atom`. Then
  re-capture BOTH benchmark baselines: token cost will FALL, and a baseline may only move on a
  documented trade (`tests/wikimem_bench/README.md`).
- **Load-bearing facts:** the lean layer already prints the bare ATOM ID for an atom hit precisely
  because a memory path is the costliest field on the row — a PAGE hit was simply never given the
  same treatment, so the cheap layer still pays full price on a third of its rows.

## 1. The measurement

`memgrep recall <symptom> <corpus>` on the two live corpora, 40 on-topic queries each (each query
a phrase the corpus's own atoms declare — the construction WM-BENCH-02 requires), `--top 10`:

| corpus | rows | page rows | locator chars | as stems | saving |
|---|---|---|---|---|---|
| USER | 400 | 140 (35%) | 17,649 | 4,769 | ~3,220 tokens / 40 queries |
| LOCAL | 384 | 150 (39%) | 23,635 | 6,171 | ~4,366 tokens / 40 queries |

So a page row spends ~90 tokens on its locator, page rows are **35–39% of all rows**, and the
saving is **~80–110 tokens per query** — comparable to the whole 283.7 tok/query budget the
conformant benchmark currently reports. This is not a micro-optimisation.

`name:` vs the file stem across the same corpora: **121 of 125 pages have `name:` == stem**; the
4 that differ are all LOCAL, and all are the documented harness-underscore case (the harness
writes `feedback_head_tee_sigpipe.md` while the page declares
`name: feedback-head-tee-sigpipe`). Both spellings currently resolve, but only because the
SCORER matches their words — not by any exact lookup.

## 2. The open decision — which identity, and is it a real key?

The atom locator is an EXACT key: WM-RCL-07 makes `recall <ATOM-ID>` an exact lookup, so the
listing's promise ("this string retrieves this thing") is literally true. A page locator must
carry the same promise or it is worse than the path it replaces — a string that looks like a key
and is really a lucky search is the kind of near-truth that costs a debugging session, not a
token.

- **`name:` (the wiki identity).** Wikilinks resolve through `name:`, so it is already the
  canonical way to address a page, and printing anything else would give a page two identities in
  two places. Needs the exact page-name hop to become a real key.
- **the file stem.** Equal to `name:` 97% of the time and free to compute from the path — but on
  the 3% it differs it is the identity the wiki does NOT link by, which is precisely the
  population where an agent will be confused.
- **a path relative to the searched root.** Needs no new data at all and captures most of the
  saving. Rejected as the primary: with several roots searched (the normal recall shape is
  LOCAL + PROJECT + USER), a bare relative path is AMBIGUOUS between roots, and resolving it
  wrongly reads a different scope's page — the exact failure the three-scope model exists to
  prevent.

Recommendation: `name:`, plus the exact-name hop, with the stem as the fallback when a page
declares no `name:` and the path as the last resort. Ambiguity across roots must be answered
(two scopes may legitimately hold the same `name:`), and the honest answer is probably to print
the qualified form only when the name is not unique in the searched set.

## 3. Why this was split out of TRDD-DO6X4ZF8

That TRDD delivered the benchmark and the layered output; this is a change the instrument makes
visible, not a defect in it. Keeping it separate is what lets DO6X4ZF8 close — an instrument that
stays open until every improvement it reveals is shipped never closes at all.

## Notes and lessons learned
