---
trdd-id: Q4AMWYCY
title: The dead-symbol check flags a card that DOCUMENTS a deletion — an obituary is not a stale citation
column: complete
created: 2026-08-12T13:53:39+0200
updated: 2026-08-12T14:21:34+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-FDV1RQEB, TRDD-GZXTSJSR]
---

# An obituary is not a stale citation

## Why (measured 2026-08-12 on the shipped v3.2.0 detector)

check 5 asks "does this STATE block cite a symbol the tree no longer has?" and answers it
correctly — but it cannot tell a **stale instruction** from an **obituary**. Live example,
TRDD-GZXTSJSR line 48, reported at **HIGH** because the token sits in the NEXT ACTION region:

> `_phase_self_budget`, was deleted 2026-08-12-verified by `d9a7189d feat!: remove …`

The card is *recording that the symbol died*. Naming it is the whole point of the sentence.
Reporting that as "cites a symbol absent from HEAD" is literally true and practically wrong:
there is nothing to repair, so the finding can only be dismissed — and a channel whose
top-severity items are dismissed on sight stops being read. FDV1RQEB predicted exactly this
("a noisy version of this is worse than nothing… equal weighting is how a useful channel
becomes noise"); this is that failure arriving.

**Scope, measured — small and worth keeping small:** 2 cards in `design/tasks/` currently carry
obituary phrasing. So this is a real recurring class, not a one-off, but it is nowhere near the
majority: most current dead-symbol findings are GENUINE (e.g. TRDD-AR9IUGIJ's NEXT ACTION really
does want to tune a knob `af499ee3` deleted). Do NOT weaken the check broadly to silence 2 cards.

## What

Suppress the finding when the citation's OWN LINE also carries a deletion marker — the card has
already said the thing the detector is about to tell it.

Sketch (to be refined against the real corpus, not from imagination):

- a deletion verb adjacent to the token — `was deleted`, `deleted by`, `removed`, `retired`,
  `no longer exists`, `gone`;
- or a commit SHA on the same line (a card that cites the commit that removed it has, by
  construction, done the homework).

Deliberately line-scoped, not paragraph-scoped: a NEXT ACTION that says "raise X" three lines
below an unrelated obituary must STILL fire. Widening the window to the paragraph would
re-introduce the false negatives this check exists to catch.

**Falsify it before shipping**: GZXTSJSR must stop firing AND TRDD-AR9IUGIJ (a genuine stale
citation) must keep firing. A change that silences both is a regression wearing a fix's clothes.

## Acceptance

- [x] A token on a line carrying a deletion marker produces NO finding
- [x] A genuine stale NEXT ACTION on a card that ALSO contains an obituary elsewhere still fires
- [x] Pinned by tests that fail before the change (both directions, not just the suppression)
- [x] The whole-board run is re-measured after: FP count down, true-positive count unchanged

## Approval log

- 2026-08-12T13:53:39+0200 — QUEUED by janitor-main-session (tier 0, own scope). Found by
  running the SHIPPED v3.2.0 detector against the real board immediately after release —
  the same loop that proved the day's probe fix worked also exposed the next defect in it.
  Not fixed inline: each detector change costs a full publish to reach production, and the
  finding is LOW-harm (dismissible noise), so it belongs in the queue rather than in a rushed
  edit at the end of a long session.
- 2026-08-12T14:21:34+0200 — COMPLETE by janitor-main-session. Implemented by a delegated
  lean-worker (`29acfb2c`) and VERIFIED first-hand, both directions, against the real board:
  **GZXTSJSR now yields 0 dead-symbol findings; AR9IUGIJ still yields 7** (whole-board 12 -> 10).
  93 tests pass, ruff clean, `mypy scripts` Success.
  Checked the thing most likely to be quietly wrong: the suppression is **line-scoped**, keyed on
  a deletion verb or a commit SHA on the token's OWN line. Paragraph scope would have re-opened
  the false negatives fixed hours earlier the same day, and would have passed a naive review —
  the two named tests (`..._obituary_line_suppresses_the_finding`,
  `..._obituary_elsewhere_does_not_shield_a_genuine_stale_next_action`) pin exactly that boundary.
  A Pyright `_root is not accessed` note on this file is PRE-EXISTING (`50e07a01`) and not a
  defect: the leading underscore is the intentionally-unused convention.
