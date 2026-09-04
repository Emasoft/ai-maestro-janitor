---
trdd-id: QJ5LP4W2
title: bound total foreground occupancy per daemon beat so a run of long bodies cannot skip a cycle
column: todo
created: 2026-09-04T05:29:46+0200
updated: 2026-09-04T05:29:46+0200
current-owner: janitor-main-session
task-type: refactor
priority: medium
severity: medium
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [daemon, scheduling, performance, session-liveness]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
external-refs: [TRDD-8BXMNQ4T]
parent-trdd: 8BXMNQ4T
---

# Bound total foreground occupancy per daemon beat

## Why this exists — the measurement is done, the decision is not

TRDD-8BXMNQ4T asked *"measure the multiplier before choosing a mechanism"*. It did.
It then spent five commits and six adversarial reviews failing to tick its own
remedy box, because **the remedy is a scheduling design decision and the card was a
measurement card**. Splitting it lets a finished measurement be finished and puts the
design question where its risk is visible.

Do **not** re-derive the measurement here. It is complete and its corrections are on
8BXMNQ4T; the load-bearing results are restated below only so this card is
self-contained.

## What was measured (8BXMNQ4T — read that card for method and caveats)

One snapshot of `global-state/daemon.log`, 6 h 22 m, fleet 15, three `interval=60`
tasks (`fleet-stop`, `oauth-rotator-tick`, `gh-notify-inbox`), 1048 task-beats:

- Beat is healthy at the median: wait med 4–5 s, p90 12–15 s against a 60 s ceiling.
- **12 stalls (`wait > 60 s`) in 5 distinct blocking episodes.**
- Every stall is explained by **cumulative foreground occupancy** — median 92.7% of
  each stall's window is filled by foreground task bodies, against **0.0%** on
  normal beats. That control is what makes the finding real rather than definitional.
- **The blockers are NOT single long bodies.** One stall is 55 s + 15 s. So a
  per-body deadline below 60 s would not have prevented it.
- `session-liveness` contributes to 8 of 12 stall rows and is the single largest
  contributor (max body 78 s). Others: `cold-cache-clear` (94 s), `gh-notify-inbox`
  (70 s), `oauth-rotator-tick`, `memory-guard`, `oauth-rotator-supervisor`.

## The problem this card must solve

The daemon's main loop is single-threaded. A beat is late by exactly the time the
loop spent in foreground task bodies since the previous dispatch. Nothing today
bounds that **sum** — only individual subprocess workloads are capped
(`_WORKLOAD_TIMEOUT_SEC`), and the bulk lane bounds only tasks already marked
`background=True`.

## Candidate mechanisms — none chosen, and two are already known to be wrong

1. **Move the blockers to the bulk lane** (`background=True`). **Rejected as stated.**
   `task_gh_notify_inbox`'s docstring argues explicitly against the lane for itself
   ("one bounded HTTP call … does not belong in the bulk lane where a 20-minute
   workload could delay it"). Worse, `session-liveness` is the pane-RECOVERY task and
   the lane SERIALISES behind one child at a time — a lane that demonstrably hosted a
   1920 s occupant on 2026-09-03. Moving session recovery there risks converting a
   78 s beat delay into a 20-minute recovery delay, which is the 2026-07-17 oauth
   starvation incident the lane's own docstring exists to record.
2. **Per-body deadline below the interval.** **Rejected by the measurement** — the
   stalls are built from individually-legal sub-60 s bodies.
3. **A per-beat foreground budget.** Track cumulative foreground time within a
   dispatch pass; once it exceeds a threshold, defer the remaining due tasks to the
   next beat rather than running them now. Untried; addresses the measured quantity
   directly. Needs a policy for which tasks may be deferred (a survival beat like
   `oauth-rotator-tick` presumably may not).
4. **Bound `session-liveness` alone.** It is in 8 of 12 rows; capping its body would
   remove most of the observed damage without touching the scheduler. Narrowest
   change, does not address the general mechanism.

## Acceptance criteria

- [ ] The fable advisor is consulted before any `scripts/daemon.py` scheduling change
      is written. This is a scheduling change to a machine-wide singleton that owns
      OAuth survival — the standing rule applies with force, not as a formality.
- [ ] A mechanism is chosen with the reason recorded, INCLUDING why the rejected
      candidates above stay rejected (or what new evidence revives one).
- [ ] A test pins the bound, and `oauth-rotator-tick` is shown still firing on
      cadence with the worst measured occupancy pattern replayed.
- [ ] Re-measure after the change with the same method (per-task `starting` markers,
      body subtracted, one log snapshot) and show the stall count falling.

## Open questions inherited from the measurement

- **Why does `session-liveness` need 78 s at all?** Never established. A detached
  bulk child cannot block the loop but can starve it of CPU, and a 1920 s
  `marketplace-refresh` child overlapped the 23:06 episode. Unexamined confound.
- **~84 s of one episode is unaccounted for** (the 54% row, 04:18:26, a 184 s wait).
  The unexplained mass clusters at 04:15–04:18 rather than spreading evenly, which
  is the signature of one unmodelled event.
- **Does the loop dispatch due tasks in registration order?** `fleet-stop` has a 0 s
  body yet stalls most often, and it is registered immediately after
  `session-liveness`. If ordering holds, that asymmetry is corroboration; it is a
  hypothesis from the `started (pid=…, tasks=[…])` line, not a reading of the
  dispatch code.

## Notes and lessons learned

- **A card whose title says "measure X" should not be the card that decides how to
  fix X.** 8BXMNQ4T's remedy box was ticked and un-ticked three times, and at least
  the last of those was not optimism — it was a measurement card being asked to
  carry a design decision it had no criteria for. The split is the fix; noticing the
  scope drift six reviews in is the lesson.
