---
trdd-id: FDV1RQEB
title: A STATE block citing a symbol the tree no longer has is undetectable — three cards stalled on it in one day
column: todo
created: 2026-08-12T10:39:24+0200
updated: 2026-08-12T10:39:24+0200
current-owner: janitor-main-session
task-type: feature
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-AR9IUGIJ, TRDD-VXFNDHXT, TRDD-50V256RH, TRDD-BRHJHWW0]
---

# Detect a STATE block whose NEXT ACTION names something that no longer exists

## Why (measured 2026-08-12 — three instances, one cause)

One breaking change, `af499ee3 feat(cadence)!: one arm per session — tier-driven renews
deleted (USER directive, TRDD-BRHJHWW0)`, silently orphaned the premises of every card that
referenced the subsystem it removed. Found only by pulling each card by hand:

| card | its NEXT ACTION | reality at HEAD |
|---|---|---|
| TRDD-AR9IUGIJ | raise `should_emit_renew`'s `dwell_s` | symbol deleted by `af499ee3` |
| TRDD-VXFNDHXT | measure the never-probed short-TTL share | the whole probe deleted by `af499ee3` |
| TRDD-50V256RH | (root cause, not a symbol) only a new session re-points skills | falsified by measurement |

Each sat 6–10 days in a WORK column asserting active work. **None of them was neglected** —
every NEXT ACTION was specific, runnable-looking and evidence-gated. That is precisely why
they stalled: a card blocked on a measurement never re-asks whether the thing being measured
still exists, and a STATE block is a claim about the tree that **nothing re-checks**.

The existing detectors do not cover this. `trdd-drift` measures AGE (all three were flagged,
which says "old", not "wrong"). `trdd-state-reconciliation` measures SHIPPED-BUT-OPEN via
released tags — it ran clean on all three, correctly, because none of them had shipped.

## What

Extend `scripts/detectors/trdd-state-reconciliation.py` with a fifth check: for each TRDD in
a non-terminal column, extract backtick-quoted `identifier`-shaped tokens from its STATE
block and report any that resolve NOWHERE in the tracked tree.

**The whole difficulty is the false-positive rate**, and a noisy version of this is worse than
nothing — it would train readers to skip the one channel that would have caught these. Design
notes, not yet decisions:

- Only scan the STATE block, and preferably only its NEXT ACTION section — that is where a
  dead symbol actually costs something.
- Only `snake_case` / `CamelCase` identifier shapes with no spaces, no slashes, no dots.
  A file path is already covered by the path's own existence; prose in backticks is not a
  symbol.
- Require the token to have EXISTED once — resolvable in `git log -S` history but not at
  HEAD. That is the exact signature (deleted, not imaginary) and it kills the largest FP
  class in one condition: a token that never existed is a typo or an external name, neither
  of which this check is for.
- SURFACE only, never mutate. Same discipline as its four siblings.

## Acceptance

- [ ] The check reproduces all three 2026-08-12 instances from their pre-fix state
- [ ] Runs clean on the current board (zero findings after today's corrections)
- [ ] A token that never existed anywhere in history produces NO finding
- [ ] Findings go through the findings ledger, not a bare drift line
