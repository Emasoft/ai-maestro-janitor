---
trdd-id: DO6X4ZF8
title: Wikimem retrieval benchmark — accuracy and end-to-end token cost, with a committed baseline
column: human_review
created: 2026-07-26T14:15:38+0200
updated: 2026-08-02T13:05:35+0200
current-owner: 2f5bc976
task-type: infra
approval-tier: 0
scope: project
release-via: publish
impacts: [memgrep, wikimem]
relevant-rules: []
external-refs: [https://github.com/Emasoft/ai-maestro/issues/96]
implementation-commits: [f0ef029, 11d476b, 9ef241d, 873f11e, 5b03519, 83fac1d, 5f98788, cf3f67a, de1a89f, d6f271f, 0dff13e, 3409ae2, ff4625a]
---

# Wikimem retrieval benchmark — accuracy and end-to-end token cost

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-26

- **Component state — SHIPPED, gating in CI.** `scripts/wikimem_bench.py` + **two** frozen
  corpora, each with a committed baseline: `tests/fixtures/wikimem-bench-conformant/`
  (**PRIMARY** — hit@1 **100%**, MRR **1.0**, 283.7 tok/query) and `tests/fixtures/wikimem-bench/`
  (**LEGACY**, pre-migration form — 21.7% / 0.3891 / 185.4). Output layers, the `recall <ATOM-ID>`
  second hop, the tiered keyphrase scorer, the recency tie-break and the cross-scope lint are all
  landed and tested.
- **AI REVIEW DONE 2026-08-02 (`ai_review → human_review`) — re-verified at CURRENT HEAD, not
  taken on the 07-26 capture's word.** Re-run mattered: `77a193c` changed `memgrep`'s
  `lint_paths` since that capture, so the committed baseline had to be re-measured against the
  binary that exists now. All green — legacy `no change`, conformant `no change` (100% / MRR 1.0
  / 273.0), lint-bench `no change` (0 FP / 0 FN, 27 codes), `cargo test --release` **127 passed**,
  `pytest` **14,109 passed / 1 skipped**, `ruff` 0. Numbers differ from the 07-26 line below
  (283.7 → 273.0 conformant; 221 → 127 cargo tests) because the corpus-path normalisation and a
  crate split landed in between — the GATE is `no change` against each corpus's own baseline,
  which is the claim that matters, not the absolute figures.
  **One defect found and fixed during the review, not deferred:** `--check` scored a
  corpus/baseline MISPAIRING as `REGRESSION 174.3 -> 273.0` instead of refusing it. Guarded in
  `f0ef029` (compare the corpus each side was measured on; exit 2, never 1).
  **Awaiting: the owner's call only.** Nothing is known-broken.
- **NEXT ACTION:** none for this TRDD — it is in `human_review`. Full gate captured 2026-07-26T19:49
  at HEAD `c8d29cc`, all green: both benchmark corpora `no change` (conformant 100% / 1.0 / 283.7,
  legacy 21.7% / 0.3891 / 185.4), `ruff` 0, `mypy` 0 over 434 files, `pytest` 13687 passed /
  1 skipped, `cargo test --release` 221 passed. The follow-ups (#25 page-row hop key, #29
  WM-SCORE-08 remainder, #31 spec-drift check) are **separate TRDDs' work**, not this one's — this
  TRDD delivered the instrument, and gating it on its own future improvements would never close it.
- **Load-bearing facts:**
  - cost is **END-TO-END** (search output + the hop it forces) — a per-call metric flatters a thin
    list that hides its hop and a fat one-shot that needs none;
  - the harness **MUST** measure the binary under test (`MEMGREP_BIN`), or every run silently
    scores whatever is on `PATH` and reports the old build's numbers as the new one's win;
  - token counts were **path-length dependent** until `corpus_arg()` normalised the corpus to a
    repo-relative path with cwd pinned — an absolute path cost 318.1 vs 283.7 for the SAME corpus,
    so a committed baseline would have encoded the capturing machine's home-directory length;
  - the migration and the scorer are **one change**: measured alone, the tiered scorer LOOKS like a
    regression (hit@10 65.2→60.9 on the legacy fixture) because substring matching had been scoring
    accidental hits there (`list` inside `listing`). Always read the **2×2**.
- **SUPERSEDED — do NOT carry forward:**
  - "benchmark not yet written / no output layers / no second hop" — all three shipped;
  - "`baseline.json` is THE baseline" — there are now TWO, and the **conformant** one is primary;
    the legacy baseline was deliberately re-captured to record a documented trade (see
    `tests/wikimem_bench/README.md`), which is the ONLY reason a baseline may move down.

## 1. Why

The owner's stated core advantage of wikimem is **grepping efficiency — fewer tokens read by an
agent to find what it is looking for**. That is a measurable property, so it must be measured;
otherwise every future change to ranking or output is argued on taste and regressions ship
silently. The owner's directive: the benchmark measures **accuracy** and **tokens**, and
development uses it version-over-version to prove there is no regression.

The instrument must exist **before** the output-layer work (TRDD to follow), because a baseline
captured after the change proves nothing.

## 2. What is measured

1. **Accuracy** — for each `(symptom query → expected atom id)` pair: is the atom returned, and at
   what rank? `hit@1`, `hit@3`, `hit@10`, MRR.
2. **End-to-end token cost to find AND obtain the atom** —
   `tokens(search output) + tokens(recall <atom-id> output)`.

The end-to-end framing is the whole point:

```
cost(basic)  = N × one_line          + 1 × full_atom
cost(full)   = N × (body + metadata + keywords + notes + superseded)
```

A per-call metric would rank `basic` best while concealing the second hop it forces, and would
punish a one-shot that needs no hop. Only the total answers *what does it cost to obtain this
fact?*, and it is what makes the layered design provable instead of merely plausible.

## 3. Design

- **Frozen fixture corpus**, committed. The live corpus changes weekly; benchmarking against it
  makes each run incomparable to the last — the opposite of a regression instrument. A `--live`
  mode stays available for spot checks, never for the gate.
- **Queries written from the SYMPTOM side** — the words a future session would actually have —
  because that is what recall ranks on. A query phrased in the answer's jargon measures nothing
  real.
- **Deterministic offline token estimator.** The benchmark compares versions of the SAME tool, so
  a stable local estimator beats an approximate remote tokenizer, and it keeps the gate hermetic
  (no network, no API key, no drift). Raw byte counts are reported alongside so every number stays
  auditable, and the estimator's bias cancels in the version-over-version delta.
- **Committed `baseline.json` + regression gate** — a run FAILS on an accuracy drop or a token
  rise beyond tolerance, wired into the test suite so a regression cannot ship quietly.

## 4. Non-goals

- Absolute billing accuracy. The estimator is a *relative* instrument; it is not a cost oracle.
- Benchmarking the live corpus in the gate (it is not reproducible).

## Notes and lessons learned
