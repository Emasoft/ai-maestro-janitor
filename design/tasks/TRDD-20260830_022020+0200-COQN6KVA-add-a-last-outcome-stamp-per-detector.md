---
trdd-id: COQN6KVA
title: add a per-detector last-outcome stamp so a decline is distinguishable from a completed pass
column: testing
created: 2026-08-30T02:20:20+0200
updated: 2026-09-01T21:55:00+0200
implementation-commits: [e1fa581d]
current-owner: janitor-main-session
task-type: feature
scope: project
project-id: ai-maestro-janitor
severity: medium
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-H8WRCW0I, TRDD-FFXGPZEI]
---

# Nothing on disk records whether a detector pass DID anything

## The gap

`.janitor/state/last-run-<detector>.ts` is written unconditionally by `dispatch.py:2159` after the
subprocess returns. It is a **cadence** marker — "a pass was attempted" — and it is correct as
that: making it conditional on success would make a declining project retry every heartbeat
instead of every 6 h, converting a quiet defect into a loud one.

But no file anywhere answers the other question. A detector that declined at its first gate leaves
a state identical to one that completed a full apply, so "did it work" is unanswerable from disk
by anyone — a human, another detector, or the fleet guardian.

Measured cost (TRDD-H8WRCW0I): a branch-protection applier declined four times a day for days
while every user-facing surface reported health. The only dissent was a log line nobody reads.

## The change

Write `.janitor/state/last-outcome-<detector>.ts` alongside the cadence stamp, carrying a short
machine-readable outcome — `applied` / `declined:<reason>` / `error:<reason>` — plus its epoch.

Additive. No migration, no rename, no reader anywhere has to change to keep working.

## What this does NOT fix, stated up front so the next card is not mis-scoped

**This does not retire the wrong inference.** The defect in TRDD-FFXGPZEI is that `last-run` is
*readable as* health by someone who never learns this second file exists. Adding a stamp does not
remove that reading — it **competes** with it, and the naive reader loses the same race as before,
because they still find `last-run` first and it still looks like an answer. Two sources, only one
discoverable by the person about to be wrong, is a strictly larger surface for the same bug.

What it genuinely buys is that it makes the rename **safe**: once an outcome stamp exists, a
reader who reaches for a renamed `last-attempt-*.ts` has somewhere to go for the question they
actually had. **Ship this first, rename second — sequenced, not chosen between** (peer argument,
AMAMA 2026-08-30; it corrected this repo's earlier framing of the two as alternatives).

## Acceptance

- [x] every detector dispatch writes `last-outcome-<detector>.ts` with outcome + epoch
- [x] a DECLINE and a COMPLETION are distinguishable from disk alone, with no log parsing
- [x] the cadence stamp is untouched — `last-run-*.ts` keeps meaning "attempted", and the due
      calculation keeps reading it
- [x] a test asserts a declining detector writes `declined:<reason>` while its cadence stamp
      still advances — the two must not be coupled
- [ ] `uv run pytest -q` + `ruff check scripts tests` + `mypy scripts/ --ignore-missing-imports`

## Notes and lessons learned

- **Do NOT make the outcome stamp the due-calculation input.** That would re-couple the two and
  reintroduce the retry-every-heartbeat failure this design exists to avoid.
- **Do NOT dual-write the same fact under two names.** The `complete`/`completed` pair drifted 232
  times fleet-wide; a drifted pair is worse than either name alone because the disagreement is
  silent and both files look authoritative. Outcome and cadence are DIFFERENT facts, which is why
  two files is right here — the prohibition is on writing one fact twice.
