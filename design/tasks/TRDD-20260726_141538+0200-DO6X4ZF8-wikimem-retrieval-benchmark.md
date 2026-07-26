---
trdd-id: DO6X4ZF8
title: Wikimem retrieval benchmark — accuracy and end-to-end token cost, with a committed baseline
column: dev
created: 2026-07-26T14:15:38+0200
updated: 2026-07-26T14:15:38+0200
current-owner: 2f5bc976
task-type: infra
approval-tier: 0
scope: project
release-via: publish
impacts: [memgrep, wikimem]
relevant-rules: []
external-refs: []
---

# Wikimem retrieval benchmark — accuracy and end-to-end token cost

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-26

- **Component state:** benchmark not yet written. `memgrep recall` currently has NO output
  layers, `--with-notes` defaults ON, and there is no `recall <atom-id>` second hop.
- **NEXT ACTION:** build `scripts/wikimem_bench.py` + the frozen fixture corpus + `queries.json`,
  then capture `baseline.json` **against the CURRENT implementation** before any output change.
- **Load-bearing facts:** the metric is END-TO-END (search output + the `recall <id>` hop), not
  per-call — a per-call metric flatters both a thin list that hides its second hop and a fat
  one-shot that needs none. Atom-level retrieval ALREADY exists (`index::recall_atom_candidates`,
  `AtomCandidate{atom_id,desc,body,keywords,ocd,lmd}`); `finalize_recall` discards `_ocd`/`_lmd`
  at the print site, so the basic layer needs no new data, only a different render.
- **SUPERSEDED — do NOT carry forward:** nothing yet.

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
