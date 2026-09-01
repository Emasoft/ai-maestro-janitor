---
trdd-id: FFXGPZEI
title: rename last-run stamps to last-attempt so the wrong inference cannot be spelled
column: backburner
created: 2026-08-30T02:18:14+0200
updated: 2026-08-30T02:22:00+0200
current-owner: janitor-main-session
task-type: refactor
scope: project
project-id: ai-maestro-janitor
severity: low
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-H8WRCW0I, TRDD-COQN6KVA]
---

# `last-run-*.ts` invites the one inference it cannot support

## The proposal (peer suggestion, AMAMA 2026-08-30)

`.janitor/state/last-run-<detector>.ts` records **when a pass was attempted**. It does not record
whether that pass did anything: `dispatch.py:2159` writes it unconditionally after the subprocess
returns, so a detector that declined at its first gate stamps exactly like one that completed.

A reader looking for "is this detector healthy?" finds a field called `last-run`, sees a fresh
timestamp, and concludes it ran. That inference is wrong and the field name invites it.

The peer's argument for renaming to `last-attempt-*.ts`: **it makes the wrong inference impossible
to spell**, whereas the note now sitting in TRDD-H8WRCW0I only protects readers who read that
card. Two sessions spent most of an investigation on exactly this confusion on 2026-08-29/30 —
78 imaginary days of a "dark lane" that turned out to be an abandoned state dir, and separately a
"the guard ran 40 minutes ago" that was a decline at gate 3.

## Why this is `backburner` — ONE reason, and it is not the one first written here

**The sole blocker is cross-repo readers.** Other plugins and the ai-maestro server consume these
filenames. A read-side fallback (below) protects THIS resolver, not theirs, so they go stale the
first time a detector writes only the new name. That is a coordination problem — enumerate those
readers and tell them, or accept the rename is blocked on them.

### The migration is NOT a blocker — do it read-side

For the due calculation only: `last-attempt-<detector>.ts` missing ⇒ fall back to reading
`last-run-<detector>.ts`. Read-only. No mutation, no migration code running on every host, no
reset, **no herd** — each stamp ages out naturally the first time that detector writes the new
name on a real run. The deprecation window costs one `or` in the resolver and deletes itself.

**Do NOT dual-write during that window.** Writing the same fact under both names is the shape
that drifted 232 times fleet-wide in the `complete`/`completed` case, and a drifted pair here is
worse than either name alone: the disagreement is silent and both files look authoritative.
**Single-write the new name; read-fall-back to the old.**

### Retracted — the "thundering herd" rationale was wrong

This section first blocked the card on a write-side migration: rename ⇒ every stamp resets to `0`
⇒ every detector on every project becomes instantly due ⇒ the next heartbeat fires all of them at
once. That framing assumed the migration must be write-side. It need not be, and the read-side
shim above costs one `or`.

Kept rather than deleted, because the failure is instructive and it is mine: **a card that cites a
solved problem as a blocker is how the real blocker stops being examined.** The herd was doing the
load-bearing work in this card's reasoning while the genuine constraint — cross-repo readers — sat
in a bullet underneath it and would have been inherited unexamined by whoever picked this up.
(Peer correction, AMAMA 2026-08-30.)

## The prerequisite: land TRDD-COQN6KVA first

An additive `last-outcome-<detector>.ts` is **not an alternative to this rename** — that was this
card's earlier framing and it was wrong. Adding a second stamp does not retire a wrong inference;
it **competes** with it, and the naive reader still finds `last-run` first and still reads it as an
answer. Two sources, one discoverable by the person about to be wrong, is a larger surface for the
same bug.

What it buys is that it makes this rename SAFE: once an outcome stamp exists, a reader who reaches
for `last-attempt-*.ts` has somewhere to go for the question they actually had. Sequenced, not
chosen between.

## Acceptance

- [ ] TRDD-COQN6KVA (the outcome stamp) has landed — this rename is unsafe before it
- [ ] every reader across the fleet is enumerated, INCLUDING outside this repo, and the
      cross-repo ones are coordinated before the rename lands here. **This is the only real
      blocker**; if it turns out there are none, this card is small
- [ ] the due calculation reads `last-attempt-*.ts` with a fall-back to `last-run-*.ts` —
      READ-side, single-write, no dual-write, no reset
- [ ] `uv run pytest -q` + `ruff check scripts tests` + `mypy scripts/ --ignore-missing-imports`

## Notes and lessons learned

- **Do NOT rename and let the stamps reset.** The disruption would be silent, machine-wide, and
  exactly the kind of self-inflicted noise that makes a user disarm the janitor. The read-side
  shim is what avoids it — this prohibition is about the naive write-side migration, not a reason
  to hold the card.
- The underlying lesson is already recorded on TRDD-H8WRCW0I and does not depend on this card
  landing: **`last-run-*.ts` answers "when was this last attempted", never "did it work".**
  This card is about making that unnecessary to know, not about establishing it.
