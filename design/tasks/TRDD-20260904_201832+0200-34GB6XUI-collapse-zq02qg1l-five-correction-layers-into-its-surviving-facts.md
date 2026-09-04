---
trdd-id: 34GB6XUI
title: collapse TRDD-ZQ02QG1L's five correction layers into its surviving facts
column: todo
created: 2026-09-04T20:18:32+0200
updated: 2026-09-04T20:18:32+0200
current-owner: main-session
task-type: docs
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
parent-trdd: L46IG69Y
external-refs: [TRDD-ZQ02QG1L]
relevant-rules: []
npt: []
eht: []
blocked-by: []
implementation-commits: []
---

# collapse ZQ02QG1L into the facts that survived it

## Why this exists

This is TRDD-L46IG69Y's EHT. L46IG69Y carried the collapse as one of its own
acceptance boxes, which was the wrong home: a box describing work on a
*different card's file* cannot be ticked by finishing L46IG69Y, so it would have
held that card open — or, worse, been quietly ignored while the card sat in a
column asserting activity.

## The task

`TRDD-ZQ02QG1L` is 404 lines carrying five correction layers. A reader must
reconstruct four reversals to extract three facts. Collapse it to the surviving
facts, with the reversals reduced to dated lessons rather than narrated in full.

The durable rule of thumb: **a superseded claim that SHIPPED earns a clause, so a
reader does not re-derive it; one that never left the draft earns nothing.**
Judgment beyond that is this task's actual work — 404 lines with five layers will
need calls those two cannot supply. (Small worked examples, if wanted:
L46IG69Y's `## Superseded` marker and OES0NN3F's empty-body note, both
2026-09-04.)

**Where this card sits in a CHAIN of effects, which is not a cycle:** ZQ02QG1L
shipped the composer -> L46IG69Y is its EHT (fixing the concision-check
interaction that shipped with it) -> this card is L46IG69Y's EHT (the doc hygiene
L46IG69Y's own box could not tick).

## Acceptance criteria

- [ ] ZQ02QG1L reads as its surviving facts, with each reversal either deleted
      (never shipped) or reduced to a dated lesson (shipped, so a reader would
      otherwise re-derive it).
- [ ] The collapsing commit's message LISTS each fact removed from the reading
      path and where it went (kept elsewhere in the card, or git history only).
      A checkbox reading "nothing true is lost" is unverifiable over 400 lines;
      an enumeration in the diff's own message is checkable by reading it.
- [ ] ZQ02QG1L's `column:` is unchanged by this work — it is **`blocked`**, so
      this is an ordinary edit to an open card and NO terminal-freeze question
      arises. Stated explicitly because a first draft of this card called it
      terminal and claimed a freeze exception; a review then correctly concluded
      the whole task was forbidden, reasoning from that false premise. **If it
      ever DOES reach a terminal column, this card is void** — the freeze permits
      only the closing edit, the append-only Approval log, and removal of a line
      that falsely and machine-verifiably contradicts the terminal column. A
      400-line readability collapse is none of the three, and would then need
      USER approval as a deliberate departure, not a claimed exception.
- [ ] L46IG69Y can then reach `complete` (this card is its `eht:` gate).

## Notes and lessons learned

- **A box that another card owns is not an acceptance criterion.** It was moved
  here from L46IG69Y for that reason. The general form: if finishing card A
  cannot tick a box on card A, the box belongs on the card that can — otherwise A
  either stalls in a work column or the box is ignored, and both hide the state
  from the only view anyone reads. What makes this a MECHANISM and not
  bureaucracy is not that a file exists: it is that the heartbeat enumerates
  `todo` cards by name every fire and `trdd-drift` can age them, while nothing
  anywhere enumerates an unticked box. Its limit, stated honestly: this card now
  joins a `todo` column that accumulates, so it is more likely to be worked than
  the box was, and not thereby likely to be worked soon.
- **The 22-column vocabulary has no state for "this card's work is DONE and it
  waits only on an EHT".** Found while columning L46IG69Y: `eht:` gates
  `complete`, so the parent must sit somewhere else, and every remaining column
  either asserts active work (`dev`, `testing` — a lie when nobody is working it)
  or a review that may not be pending. `eht:` is the mechanism and the column
  cannot express it. Recorded because it will recur on every card with an EHT.
