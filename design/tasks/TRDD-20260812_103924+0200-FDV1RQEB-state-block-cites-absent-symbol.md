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

## PROTOTYPE MEASURED 2026-08-12 — the design holds, with one refinement

Ran a throwaway implementation of exactly the predicate above (identifier-shaped backticked
token, absent from `scripts`/`tests` at HEAD, present in `git log -S` history) over the STATE
block of every non-terminal card on the board.

| token | at HEAD | deleted by | verdict |
|---|---|---|---|
| `should_emit_renew` (TRDD-AR9IUGIJ) | no | `af499ee3` | FLAGGED — reproduces today's instance |
| `resolve_ttl_minutes` (TRDD-VXFNDHXT) | no | `af499ee3` | FLAGGED — reproduces today's instance |
| `_phase_self_budget` (TRDD-GZXTSJSR) | no | `d9a7189d` | FLAGGED — a NEW find |
| `findings_ledger` (control) | yes | — | not flagged |

**One hit across the whole board, zero false positives observed.** The "existed once in
history" condition is carrying the weight, exactly as designed — a token that never existed
is a typo or an external name and is silently skipped.

**The refinement the prototype surfaced:** the new find is an ANALOGY, not a dependency —
*"a login-nudge phase must be LATE and fail-open, like `_phase_self_budget`"*. The invariant
survives; only the worked example rotted. A dead symbol in a NEXT ACTION blocks the card; a
dead symbol in an illustration merely misleads. **Severity must depend on WHERE in the STATE
block the token sits**, or the check reports a one-word doc repair with the same weight as a
card that cannot proceed — and equal weighting is how a useful channel becomes noise.

(TRDD-GZXTSJSR's line is already repaired, re-pointed at `_phase_self_cost_alarm` /
`_phase_user_presence_breadcrumb`.)

## Acceptance

- [ ] The check reproduces all three 2026-08-12 instances from their pre-fix state
- [ ] Runs clean on the current board (zero findings after today's corrections)
- [ ] A token that never existed anywhere in history produces NO finding
- [ ] Findings go through the findings ledger, not a bare drift line
