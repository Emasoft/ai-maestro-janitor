---
trdd-id: N7NZOYAK
title: check2 lets one DONE-marked NEXT-ACTION line mask every still-pending one
column: testing
created: 2026-08-02T06:06:23+0200
updated: 2026-08-02T13:40:00+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
severity: HIGH
scope: project
release-via: publish
relevant-rules: []
implementation-commits: [77b9ba2]
---

# check2 lets one DONE-marked NEXT-ACTION line mask every still-pending one

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**FIXED the same session it was filed** (`backburner → testing`). The two regression tests were
written first and the first one FAILED against the old code with exactly the predicted
`assert False is True` — so the bug is reproduced, not inferred. The one-token fix then turned it
green: `54 passed` in `test_trdd_common.py`, `184 passed` across the TRDD suite, ruff clean.

**The safety argument is a proof, not a sample.** `not any(done)` means *all lines not-done*;
`any(not done)` means *at least one not-done*. All-implies-at-least-one, so every card the old
code called remaining is still remaining — the change can only ADD remaining-work signals and only
REMOVE closeable-candidate ones. It cannot silently close anything. Measured on the live board to
match: closeable-candidate 2 → 1, and the one that moved is TRDD-dfc0959a, which genuinely has
pending validation.

Awaiting: ride the next publish. `release-via: publish` ⇒ terminal column will be `published`.

**Found by hitting it**, not by reading code: while refreshing TRDD-dfc0959a's STATE block on
2026-08-02 I wrote a table row that happened to contain the phrase `NEXT ACTION` and the word
`DONE`. That one line flipped the whole card from `partially-shipped-review` to
`closeable-candidate` — while its real, still-pending next action sat four lines below,
untouched. A prose edit silently suppressed the card's remaining-work signal.

## The defect

`scripts/lib/trdd_common.py::check2_has_remaining_work`:

```python
na_lines = [m.group(0) for m in _NEXT_ACTION_RE.finditer(record.body)]
if na_lines and not any(_DONE_MARKER_RE.search(ln) for ln in na_lines):
    return True
```

`not any(done)` means: *"there is remaining work only if NONE of the next-action lines is
done-marked."* So a single done-marked line makes the whole card read as finished, no matter how
many pending next actions accompany it.

The intended reading — stated in the function's own docstring — is the opposite:

> *scoped to the line, so a ✅ on a finished SUB-part can't mask a still-pending next action*

The per-line scoping was added for exactly this failure (TRDD-15ECPBSA's precision fix, after the
whole-body check mislabeled partly-done TRDDs as closeable). It fixed the case where the ✅ sits on
a NON-next-action line, and re-introduced the same masking one level down: now the ✅ only has to
sit on *some other* next-action line.

**The fix is one token** — quantifier and negation swap places:

```python
if any(not _DONE_MARKER_RE.search(ln) for ln in na_lines):
    return True
```

Read: *"remaining work if ANY next-action line lacks a done marker"* — which is what the docstring
says and what a reader assumes.

## Why this is HIGH and not cosmetic

check2 is not a display filter. It is the gate that separates `closeable-candidate` from
`partially-shipped-review` — the one signal standing between an audit sweep and closing a card
whose work is not finished. It exists specifically to stop that over-claim. A false *negative*
here is the most expensive direction the reconciler can be wrong in: nobody re-reads a card the
board says is done.

The trigger needs no malice and no unusual authoring. Any card that mentions a next action twice —
one done, one pending, which is the ordinary shape of a STATE block that records progress — is
mis-signalled. And because `_NEXT_ACTION_RE` matches the phrase ANYWHERE on a line, prose *about*
next actions ("the NEXT ACTION list was never updated") counts as a next-action line.

## Verification (write these first — the current tests do not fail)

Every existing `check2` test uses a body with exactly ONE next-action line, where the two
semantics agree, so the suite stays green through the bug. The regression test must have **two**:

- body with a done-marked next-action line AND a pending one ⇒ `True` (fails today, returns
  `False`).
- body with two done-marked next-action lines and none pending ⇒ `False` (must stay).
- the existing single-line cases ⇒ unchanged.

Then re-run the reconciler over the live board and diff the labels: the count of
`closeable-candidate` should only ever DROP. Any card that moves the other way means the new
reading is wrong, not the old one.

## Do NOT bundle

Working the same board turned up a second, separate reconciler precision issue — `check4` treats
**any** TRDD id mentioned in the body of a card whose prose trips the same block-language scan as a
prose-named blocker, so a genuinely-held card that cites terminal siblings for REUSE (TRDD-2C8XFOW9 cites
EQ792YPX and T7N67AQP that way) reports permanent phantom "stale blockers". That is noise, not a
wrong close, and it is a different mechanism. Separate card, per rule 13 — not a second item here.

## Notes and lessons learned
