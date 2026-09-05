---
trdd-id: 34GB6XUI
title: collapse TRDD-ZQ02QG1L's five correction layers into its surviving facts
column: todo
created: 2026-09-04T20:18:32+0200
updated: 2026-09-05T03:24:14+0200
current-owner: main-session
task-type: docs
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
external-refs: [TRDD-ZQ02QG1L, TRDD-L46IG69Y]
relevant-rules: []
npt: []
eht: []
blocked-by: []
implementation-commits: []
---

# collapse ZQ02QG1L into the facts that survived it

## Why this exists

An UNGATED chore. It began as one of TRDD-L46IG69Y's acceptance boxes, which was
the wrong home — a box describing work on a *different card's file* cannot be
ticked by finishing L46IG69Y — so it became this card, wired as L46IG69Y's
`eht:`. That was wrong too, and more interestingly so: it made a finished,
tested fix wait on a readability cleanup **I** had decided was worth doing.
Asked directly, the USER dropped the gate (2026-09-05); L46IG69Y closed
`complete` and this card stands on its own, to be picked up when it is worth
someone's time or dropped if it never is.

**Nothing waits on this.** If that stops being true, say so here.

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

**How it got here, which is a chain and not a cycle:** ZQ02QG1L shipped the
composer -> L46IG69Y was its EHT (fixing the concision-check interaction that
shipped with it) -> this card came out of L46IG69Y as doc hygiene its own box
could not tick. The chain ends there: the `eht:` link was dropped, so this card
gates nothing.

## ⏵ 2026-09-05 — THE PREMISE UNDER BOX 3 IS NOW FALSE, AND THE TASK IS FORBIDDEN AS WRITTEN

**I closed ZQ02QG1L to `complete` today** (`87e13001`) — its blocker L46IG69Y had gone terminal,
so `pre-block-column: complete` was restored mechanically. That was correct on the rules and it
**falsifies box 3 below**, which reads *"it is `blocked`, so this is an ordinary edit to an open
card and NO terminal-freeze question arises."*

ZQ02QG1L is now terminal, and rule 12 freezes terminal cards: *no body edits on `complete`*, with
narrow exceptions (the closing edit; an `## Approval log` append; archival; removing a body line
that FALSELY and machine-verifiably contradicts the terminal column). **A readability collapse is
none of those.**
*Why the obvious counter-argument fails:* one might say a collapse is fact-PRESERVING, so rule
7's "mechanical repair, no fact change" carve-out should cover it. It does not, on three grounds.
The text is categorical with an ENUMERATED exception list — and every listed exception is itself
fact-preserving, which would make all four redundant if "preserves facts" were the test. Rule 7
answers *"do I bump `updated:`?"*, not *"may I edit?"*; rule 12 answers the second and names
`updated:` among the only things that may change, so it already contemplates and constrains rule
7's mechanism. And this card calls the work *"judgment"*, which is not format/syntax-only even on
rule 7's own terms. *(Also: "preserves facts" understates it — the spec DELETES never-shipped
reversals, which are true statements about the record, not about the subject.)* So the earlier review that called this whole task forbidden — which box 3 records
as having reasoned from a false premise — now reaches the same conclusion from a TRUE one.

**Box 3's self-enforcement worked exactly as designed**, and that is worth noting rather than
patching: whoever picks this up reads ZQ02QG1L to collapse it and sees `column: complete` on the
way in. The card fails closed. Nobody was going to collapse a frozen card by accident.

**THE OPEN DECISION, not mine to take silently — the column is deliberately left `todo` so it is
visible rather than quietly parked:**
1. **Cancel it.** The card says "Nothing waits on this", and the USER already dropped its gate.
   A 404-line card nobody must read again may simply not be worth an exception.
2. **Re-scope to a permitted form** — the collapse lands as a NEW card carrying the surviving
   facts. Rule 12's own remedy is "new work = new TRDD".
   **⚠ MY FIRST WORDING OF THIS OPTION CONTAINED THE VIOLATION IT EXISTS TO AVOID:** I wrote
   "with ZQ02QG1L left frozen **and pointing at it**" — adding that pointer IS a body edit to a
   frozen card. Two legal salvages:
   - **Drop the pointer.** The NEW card carries `external-refs: [ZQ02QG1L]`; ZQ02QG1L is
     untouched. Discovery runs the other way, and via `grep -rl ZQ02QG1L`. Slightly worse for a
     reader who lands on ZQ02QG1L first, entirely legal.
   - **`superseded-by:`** — rule 12 names it as permitted on a terminal card. But it ASSERTS
     that ZQ02QG1L is superseded, which would be false if the new card is a readability
     distillate rather than a replacement. Legal, and probably wrong here.
3. **Seek a freeze exception** for readability-only edits to terminal cards. That is a rules
   question, not a task, and it would need the USER.
4. **Recognise the task may simply have EVAPORATED — not a decision anyone owes.** The
   readability problem is now self-limiting: ZQ02QG1L is terminal, nobody must work FROM it
   again, and its correction layers are exactly the audit trail rule 12 exists to preserve. The
   collapse earned its keep while the card was live and a reader had to ACT on it; on a frozen
   card the cost of 404 lines is paid only by whoever chooses to read it. This is materially
   different from option 1, which still frames it as a pending judgment call.

*What must NOT happen: reverting ZQ02QG1L to `blocked` to make this card executable again.* The
close was mechanically correct; un-closing a card to unblock a chore about that card would be
falsifying board state to suit a convenience.
**The objection a future reader WILL re-run, answered here so they need not:** *"`complete` means
the work is done; this chore is known outstanding work on that card; so the close was
premature."* It fails because **34GB6XUI is a chore ABOUT the card, not work OF the card** — this
card's own text says so: *"an UNGATED chore… it made a finished, tested fix wait on a readability
cleanup I had decided was worth doing"*, and *"Nothing waits on this."* The USER dropped that
gate precisely so ZQ02QG1L would not hang on a documentation preference; reverting the column
would reinstate, by side-effect, the exact dependency a human deliberately removed. The restore
was also mechanical — `pre-block-column: complete` recorded a judgment made 2026-09-04, before
this card was a live consideration.

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
      the whole task was forbidden, reasoning from that false premise. Whoever
      works this card must read ZQ02QG1L to collapse it and will see its column
      on the way in, so the condition enforces itself through the task — no prose
      warning needed, and this card is in no position to carry one after
      criticizing exactly that below.

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
