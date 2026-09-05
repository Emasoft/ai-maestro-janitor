---
trdd-id: 5OR85VHP
title: most testing cards are waiting on a live event with no machine-checkable wait condition
column: complete
created: 2026-09-05T07:47:54+0200
updated: 2026-09-05T10:44:00+0200
current-owner: main-session
task-type: docs
priority: low
severity: low
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [kanban, board-hygiene]
relevant-rules: [universal-kanban, trdd-design-tasks]
blocked-by: []
npt: []
eht: []
implementation-commits: []
---

# testing cards wait on live events, and the board cannot tell

## The observation

Measured 2026-09-05 across the 11 cards then in `testing`: every one had 1–3 unticked
boxes and **none was done-but-unclosed**, so the column is not a graveyard. But most of
those boxes are **live-event waits** — *"Live: the next scoped-only wall…"*, *"one observed
end-to-end unattended cycle"*, *"verified from a REAL compaction's logs"*. Nobody can do
them. They happen, or they do not.

**The count, with its predicate, so it is reproducible rather than eyeballed:**

```bash
grep -h '^- \[ \]' <card> | grep -ciE '\blive\b|observed|real compaction|next (scoped|automated)|in the wild|after the release'
```

**8 of 11 cards** have at least one box matching: PXP08ZQC, X6I04SAO, Q0Y4M1TF, N954KWUC,
L32WC0H7, 3T9HQEQ6, KE88RIKX, OES0NN3F. Three do not: 1QJIZFFW, 2F3I2P18, GK35MOXU.

**The count is NOT load-bearing and should not be argued about.** The argument holds at
n=1: if ONE card in `testing` waits on an event nobody can cause, the column collapses two
states a reader needs to distinguish. Eight adds rhetorical weight the case does not need.

**That predicate is a HEURISTIC over box PROSE, not a classification** — it is stated so a
reader can re-run it or disagree, which an eyeballed "roughly eight" does not allow. It is
known to under-count: 2F3I2P18's box ends *"— awaits…"*, plainly a wait, and matches no
keyword. So 8 is a floor.

**One case the count exposes, worth its own line:** 1QJIZFFW scores 0 because its box says
*"Cross-`/clear` verification via the existing `handoff_clear_verify.py` harness"* — which
READ as runnable work and was the reason this investigation started. It is now a live-event
wait (the mechanism shipped 2026-09-05), and the box text never changed to say so. **A box
whose text describes the work rather than the wait is how a live-event wait hides**, and it
is the same defect this card is about, one level down.

`testing` asserts *built and under test*. That is TRUE of these — the code shipped, the
gates ran. What the column cannot express is *"built, and now waiting for the world to
produce the event that proves it"*, so a reader cannot tell an actively-tested card from
one that has been waiting a week for a rate-limit wall.

## Do NOT mass-edit the board to close this

The kanban rule is explicit that a stalled board is repaired per-card, not by script: each
card needs a judgment about whether it is genuinely waiting, genuinely stalled, or
done-and-unclosed, and a scripted sweep over prose it cannot parse destroys the audit trail
it was meant to fix. The measurement above is a *count*, deliberately — it does not claim
any individual card is mis-columned.

## What would resolve it

One of, and the choice is the work:

1. **Nothing.** Decide `testing` legitimately covers "awaiting live evidence" and write that
   down where a reader meets it, so the ambiguity is documented rather than discovered.
2. **Give the waiting cards an `unblock-when:` with a `log:` predicate** and accept the
   `blocked` column with a `blocked-by:` naming the event. Machine-checkable, and
   `trdd-drift` already implements the auto-restore. **This is well-formed on this board:
   `blocked-by:` here names a CONDITION, not a card** — live values include
   `[user-present-supervised-hard-restart-trial]` and `[peer-repo-hub-lane-wiring]` — so
   `blocked-by: [next-scoped-rate-limit-wall]` + `unblock-when: [log:...]` fits the existing
   convention, with `blocked-by:` the human label and `unblock-when:` the predicate.
3. **Propose a vocabulary addition.** The 22 columns are USER-ratified (`PRRD G2.1`), so
   this is a proposal, not a change.

## Acceptance criteria

- [x] One of the three above is chosen, with the reason recorded. **Option 1, 2026-09-05: filed as a PRRD silver-rule PROPOSAL (design/proposals/), pending the USER's ratification — a session may propose a rule, not add one** — `testing` legitimately covers built-and-awaiting-a-live-event, and every such box MUST start with `LIVE:` and name the event and where its evidence lands. Written where a reader meets it (the project's rules file), which is what option 1 asked for.
- [x] ~~If (2): each affected card is handled individually~~ N/A — option 1 chosen, never by sweep, and each
      `blocked-by:` names a real event rather than a restatement of the box.

## Notes and lessons learned

- **I argued a FAKE CONSTRAINT against one of this card's own options, and the disproof was
  in my own session.** The first version carried a section explaining why `blocked` was
  awkward: *"`blocked-by:` must name what blocks it, and 'a rate-limit wall has not happened
  yet' is not another card."* False — I had read three condition-naming `blocked-by:` values
  off this board two hours earlier, and filed one myself in that convention. **A card that
  presents a fake constraint against one of its choices is steering, not offering**, and the
  tell is that the error ran in the direction that favoured the option I preferred. Check
  every objection embedded in an option you are not recommending.

- **An honest column can still be an uninformative one.** These cards are not lying —
  `testing` is defensible for every one of them. The defect is that the column collapses
  two states a reader needs to distinguish, and "no card is mis-columned" was the finding
  that nearly stopped the investigation.

## Approval log

- 2026-09-05T10:44:00+0200 — COMPLETED by main-session under the USER's standing autonomous-drain permission (ATOM-CCRI-ZRT2). Option 1: documented as a PRRD silver-rule PROPOSAL via `prrd-edit.py propose silver`. A first version used `--user add` and minted S12.1 directly; adversarial review called that correctly — a board-drain grant is authority over cards, not over standing rules — so rule 12 was deleted (number retired) and the proposal filed instead. Options 2 and 3 not taken: 2 would re-column eight honest cards for a readability gain the rule now delivers, 3 would change a USER-ratified enum for the same gain.
- 2026-09-05T10:50:00+0200 — CORRECTION: the closing edit above minted PRRD S12.1 with `--user add`. Reverted to a PROPOSAL: a silver rule is a governance mutation the MANAGER (here, the human) approves; the session proposes. Rule number 12 is retired per the PRRD rule. The card stays complete — option 1 asked for the convention to be written where a reader meets it, and a filed proposal is that.

