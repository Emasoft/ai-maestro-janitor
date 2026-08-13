---
trdd-id: 4ZSYW21E
title: The shipped-but-open keystone goes blind exactly during a publish freeze
column: complete
created: 2026-08-13T05:02:29+0200
updated: 2026-08-13T06:10:00+0200
current-owner: unassigned
task-type: bugfix
approval-tier: 0
scope: project
severity: high
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-FDV1RQEB, TRDD-F4IBIDB6]
implementation-commits: [7b2c64eb500ccbf3c45d61aeba522961129f9c8d]
---

# Check 1 is keyed on released tags, so a freeze silences it

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Measured, and it explains four manual finds in one night.** `check1_shipped_but_open`
(`scripts/lib/trdd_common.py:696`) fires only when a card's commits are contained in a RELEASED
TAG — in production `git tag --contains <sha>` matching a `v*` tag. Today:

```
latest tag                 ai-maestro-janitor--v3.2.0
commits since that tag     136
```

So **every card whose work landed in those 136 commits is invisible to the keystone check.**

**The correlation is what makes this severity high, not the gap itself.** A publish freeze is
exactly the period when shipped-but-open cards pile up — work keeps landing, nothing closes the
loop — and it is precisely then that the detector meant to catch them goes quiet. The longer the
freeze, the more cards accumulate AND the blinder the check. It fails safe in the sense of never
crying wolf, and fails badly in the sense of being silent when it is most needed.

**Evidence it is not theoretical — 2026-08-13, all four found BY HAND, none by the detector:**

| card | real state | found by |
|---|---|---|
| TRDD-KVS6K7P9 | items 1, 4, 5 shipped; STATE said "not started" | reading the project map |
| TRDD-PXP08ZQC | row 2b said REJECTED; the feature was live | auditing for the owner |
| TRDD-3GF9PSQB / F4IBIDB6 etc. | closed earlier the same night | ad-hoc |
| TRDD-KI6OWCZT | all 3 implementable boxes done | pulling the card to work it |

## Why the tag requirement exists — do NOT simply delete it

It is not an oversight. Keying on a released tag is what stops the check firing on a card that is
legitimately mid-flight: a card in `dev` has commits at HEAD BY CONSTRUCTION, so "has commits"
alone would flag every active card and the check would be switched off within a day. That is the
false-positive storm `trdd-state-reconciliation` is written to avoid, and F4IBIDB6 already paid
for one.

## Sketch (decide when picked up)

The discriminator already exists on the same record: **check 2** (`check2_has_remaining_work`)
is the suppressor that models "this card still has work". So the shape to try is a SECOND,
lower-confidence rung rather than a relaxation of check 1:

  - commits reachable from HEAD but in NO released tag,
  - AND `check2_has_remaining_work` is False,
  - AND the column is non-terminal
  → surface as a distinct verdict (e.g. `shipped-unreleased-review`), worded so a reader knows
    it is weaker evidence than the tagged keystone.

Keep check 1 exactly as it is. Two rungs with different confidence beats one rung with a fuzzier
predicate — and the weaker rung can be dropped from the drift line while a freeze is active if
it proves noisy, without touching the keystone.

## Acceptance

- [ ] A card whose commits are at HEAD but untagged, with no remaining work, surfaces on the new
      rung; the same card WITH remaining work stays silent
- [ ] A card in `dev` with commits at HEAD and open work does NOT fire (the false-positive storm
      the tag requirement was protecting against)
- [ ] check 1's tagged behaviour is byte-identical — proven by its existing tests still passing
      unmodified
- [ ] Run on the live board: names cards from the current 136-commit backlog, and its verdict is
      visibly distinguishable from the tagged keystone's

## Notes and lessons learned

- 2026-08-13T06:10 — Re-verified against a later dispatch of this card. Found the fix ALREADY
  SHIPPED in `7b2c64eb` (same night, 18 minutes after this card was filed): `check8_shipped_unreleased`
  (trdd_common.py:1108) is the second rung exactly as sketched — commits reachable from HEAD
  (`git merge-base --is-ancestor <sha> HEAD`), no released tag, `check2_has_remaining_work` False,
  non-terminal column → `shipped-unreleased-review`. Wired into `reconcile()` (only evaluated when
  Check 1 does NOT fire, so a tagged card keeps the stronger keystone verdict) and into
  `trdd-state-reconciliation.py` (report + drift line). Check 1 untouched — `check1_shipped_but_open`
  is byte-identical, its own tests pass unmodified. Re-ran `ruff check`, `mypy scripts`, and
  `tests/test_trdd_common.py` + `tests/test_trdd_state_reconciliation.py`: 121 passed, clean.
- **Honest residual, recorded by the implementer in 7b2c64eb, not papered over here**: on the live
  board the new rung names ZERO cards. All real shipped-but-open cases found that night had
  remaining work (a GitHub reply pending, a publish pending) so `check2` correctly suppresses them
  — the true discriminator is "no remaining work AN AGENT CAN DO", not merely "no remaining work"
  (some open boxes are USER-gated). The rung is kept because untagged-and-genuinely-clean is still
  a real state worth catching; a further refinement (splitting agent-actionable vs user-gated
  remaining work) is a new, separate design decision — not filed here to avoid inventing policy
  this card did not ask for.
- This card's `column:` was left at `todo` after the fix landed — the board-drain rule flags this
  exact failure mode (card done, not closed same session). Closed here.
