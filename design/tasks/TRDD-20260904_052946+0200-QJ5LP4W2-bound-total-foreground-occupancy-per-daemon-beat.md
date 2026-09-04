---
trdd-id: QJ5LP4W2
title: bound total foreground occupancy per daemon beat so a run of long bodies cannot skip a cycle
column: todo
created: 2026-09-04T05:29:46+0200
updated: 2026-09-04T14:30:41+0200
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

**Why this card is INDEPENDENT — not 8BXMNQ4T's EHT, and carrying no `parent-trdd:`.**
Two decisions, both deliberate:

1. **No `parent-trdd:`** — the TRDD rule is explicit that a derived card is *depth-1*:
   empty `npt:`/`eht:`, **never a `parent-trdd:`**. A first version of this file set one.
   Keep it that way: this card must not grow an `eht:` either, or closures start
   requiring an unbounded graph walk instead of a flat check.
2. **Not listed in 8BXMNQ4T's `eht:` — this is TRDD clause 13's THIRD branch.** Clause 13
   says: *"If you catch yourself writing 'and also do X', X is an NPT, an EHT, **or its own
   TRDD**."* Three peer options, and only the third carries no gate. NPT is wrong (nothing
   here is a prerequisite *for* the measurement); EHT is defensible but would mean
   8BXMNQ4T cannot reach `complete` until the daemon is fixed, keeping a finished
   measurement open — the scope drift the split was performed to cure. So: its own TRDD,
   cross-referenced.
   **A first version justified this by asserting `eht:` "exists for effects OF A CHANGE".
   That qualifier is not in the rule** — clause 9 defines only the gating semantics. It
   was a gloss supplied to reach the closure I wanted, which is the same defect as a
   manufactured number, in a register with nothing to grep. The outcome is unchanged; the
   argument is now the rule's own text.

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
- ~~**Does the loop dispatch due tasks in registration order?**~~ **ANSWERED YES from
  the dispatch code, 2026-09-04 — and the answer carries a design precedent the card
  should use.**

  **⚠ The first version of this answer cited `_run_due_pass`. NO SUCH FUNCTION EXISTS**
  — the name was invented, and a reader grepping it finds nothing. The real one is
  **`_run_due_tasks` (`scripts/daemon.py:3069-3105`)**, whose dispatch loop at `:3087`
  is a plain `for task in tasks:` with **no sort** on the foreground path.

  **The list is order-as-written at runtime, checked end to end** (the first version
  asserted this from the loop alone, without reading where `tasks` comes from):
  `_build_tasks` (`:2975`) `return`s a flat literal of 15 `Task(...)` entries ending at
  `:3007`; `main` does `tasks = _build_tasks()` (`:3433`) and passes it straight to
  `_run_due_tasks(tasks, yielded)` (`:3557`); `grep` for `tasks.sort` / `sorted(tasks)`
  / `reverse` / `shuffle` finds **nothing**. The apparent gaps in the `Task(` line
  numbers (3002–3004) are a comment block, not conditional registration.

  **Scope:** this is a claim about the MAIN LOOP only. `_build_tasks()` has a second
  call site at `:3634` inside `_run_task_child` (`:3620`) — a separate child path,
  irrelevant to beat ordering. Do not read "order-as-written at runtime" as a
  whole-file claim.

  Order: … `github-config-audit` (`:2996`), **`session-liveness` (`:2998`)**,
  **`fleet-stop` (`:2999`)**, `cold-cache-clear` (`:3000`), `gh-notify-inbox` (`:3001`),
  `integrity-repin`, `oauth-recovery`.

  **⚠ AND THE ADJACENCY READING IS THE WRONG ONE — it tilts the very decision this card
  exists to make.** I wrote that `fleet-stop` stalls "because it is dispatched directly
  after the largest foreground body". That is under-determined: the measurement says
  stalls are **cumulative across multiple bodies** ("one stall is 55 s + 15 s"; "the
  blockers are NOT single long bodies"), and 78 s is `session-liveness`'s *max*, not its
  typical. Meanwhile `cold-cache-clear` and `gh-notify-inbox` are registered *after*
  `fleet-stop`, so they cannot contribute to its wait in the same pass at all.

  **The position-in-chain reading is better supported.** `fleet-stop` is **11th of 15**,
  with **ten** predecessors, so its wait accumulates all ten bodies ahead of it. That
  explains a 0 s-body task stalling most often **without needing `session-liveness`
  specifically**.

  **Counted, because the first two versions of this paragraph both got it wrong** — it
  said "tenth of fifteen … all nine predecessors", off by one, in a commit whose subject
  was a miscitation:

  | # | task | # | task | # | task |
  |---|---|---|---|---|---|
  | 1 | marketplace-refresh | 6 | memory-guard | 11 | **fleet-stop** |
  | 2 | fleet-plugins-update | 7 | cache-prune | 12 | cold-cache-clear |
  | 3 | version-update | 8 | rules-cleanup | 13 | gh-notify-inbox |
  | 4 | oauth-rotator-supervisor | 9 | github-config-audit | 14 | integrity-repin |
  | 5 | oauth-rotator-tick | 10 | session-liveness | 15 | oauth-recovery |

  **And it is behind FOUR of the six named contributors, not "every" one** — the earlier
  wording said both "behind every named foreground contributor" *and* "`cold-cache-clear`
  and `gh-notify-inbox` are registered after `fleet-stop`", four sentences apart. Both
  cannot hold. Ahead of it: `oauth-rotator-supervisor`, `oauth-rotator-tick`,
  `memory-guard`, `session-liveness`. Behind it: `cold-cache-clear`, `gh-notify-inbox`.
  The "behind everything" phrasing is what made the cumulative reading sound decisive, so
  the correction matters.

  **What this does and does NOT do to the candidate choice — third attempt at this
  balance, and the first two both tilted.** v1 said the adjacency proved candidate 4;
  v2 said the chain is evidence *for* 3 *whereas* adjacency argues for 4; v3 said 4
  "cannot close the gap". **All three were verdicts, and the third performed neutrality
  while pre-loading the answer in the sentence before it** — "cannot close the gap"
  asserts an insufficiency nobody quantified.

  **What is actually established:** contributors other than `session-liveness` also
  accumulate into `fleet-stop`'s wait (four of the six named precede it). **What is
  NOT established:** how much stall mass those ten predecessors contribute *versus*
  `session-liveness` alone — nothing here measures that, and the card's own data has
  `session-liveness` in **8 of 12** rows as the single largest contributor, which is
  consistent with capping it closing *most* of the gap.

  **So: whether candidate 4 alone suffices is UNMEASURED.** That is the whole brief.
  The choice is the advisor's, and this card supplies the chain, not the verdict.

  **The precedent, and it is the useful half.** The BACKGROUND lane deliberately does
  NOT use list order: `_next_bulk_task` (`:3065-3066`) picks `min(due, key=_last_run)`
  — least-recently-run — and the comment at `:3084-3085` says why in the daemon's own
  words: *"Decided ONCE, before the loop, so the choice cannot depend on where we are
  in list order — that dependence is exactly the starvation `_next_bulk_task` cures."*

  **The daemon therefore already classifies list-order dependence as a starvation bug,
  and has already fixed it — for the bulk lane only. The foreground loop still has the
  identical dependence.**

  **⚠ But "the fix already exists, just port it" OVERSTATES — retracted.** The two are
  not the same problem shape:

  | | `_next_bulk_task` | a foreground budget |
  |---|---|---|
  | decides | which ONE due task **runs** | which due tasks are **deferred** |
  | when | every pass, unconditionally | only once a budget is exceeded |
  | need | prevent starvation of a lane | stop a beat overrunning its interval |
  | survival tasks | none — every bulk chore is deferrable | **`oauth-rotator-tick` must NEVER be deferred** |

  `min(due, key=_last_run)` is a pure **fairness** rule with no concept of a task exempt
  from the policy.

  **⚠ "Ported verbatim it would defer `oauth-rotator-tick`" was a category error — and
  the real argument is stronger.** Verbatim, `_next_bulk_task` never sees that task at
  all: its candidate list is `[t for t in tasks if t.background and …]` (`:3065`) and
  `oauth-rotator-tick` is **foreground** — `_build_tasks`' own preamble says the lane
  exists so that *"the 60 s survival beats below (`oauth-rotator-tick` above all) are
  never starved behind them"*. Porting therefore *means* dropping the `background`
  filter, at which point "verbatim" no longer describes anything.

  **⚠ The replacement was ALSO wrong, and inverted — second failed attempt at this
  paragraph.** It read: *"among due tasks a 60 s survival beat is systematically the
  most-recently-run … least-recently-run would defer it structurally, on every pass."*
  The premise is right — `_last_run()` is a timestamp (`:2810-2814`), and among **due**
  tasks a 60 s beat's is ≈ now while an 1800 s neighbour's is ≈ 1800 s old, so the beat
  IS the most-recently-run. The conclusion inverts the code: `min(due, key=_last_run)`
  picks the **smallest** timestamp — the **least**-recently-run — so that rule never
  selects the frequent beat at all.

  **The honest finding is that the port's semantics are UNDERSPECIFIED, and its effect
  on the survival beat is therefore undetermined in EITHER direction:**

  | if the ported rule selects… | then `oauth-rotator-tick` is… |
  |---|---|
  | **who RUNS** (the bulk lane's meaning) | never selected → **starved** |
  | **who is DEFERRED** (a budget's meaning) | never deferred → **protected** |

  The bulk lane selects who *runs*; a foreground budget selects who is *deferred*. Those
  are opposite polarities, and until the port fixes one, no claim about the survival
  beat follows. **Two attempts here reached for a concrete failure mode the evidence
  does not pin down** — the first a category error (`t.background` filters the beat out
  entirely), the second this inversion, each presented as sharper than the last.

  **What stands without any of that, and is sufficient on its own:
  `min(due, key=_last_run)` has NO exemption concept.** A foreground policy needs
  fairness **plus a priority floor** for tasks that must never be deferred, and the
  floor has no precedent in this file.

  **What IS directly transferable is the STRUCTURE, and it is the valuable half:**
  *decide the budget/deferral set ONCE, before the loop*, so the outcome cannot depend on
  where the loop happens to be. A budget computed mid-loop would reintroduce the exact
  order dependence `_next_bulk_task` was written to cure. Take the shape and the
  rationale; the policy still has to be designed.

  Read-only source reading; no `daemon.py` change written, so the advisor gate on the
  first acceptance box is untouched. This narrows what the advisor is asked, rather
  than pre-empting it.

## Notes and lessons learned

- **A card whose title says "measure X" should not be the card that decides how to
  fix X.** 8BXMNQ4T's remedy box was ticked and un-ticked three times, and at least
  the last of those was not optimism — it was a measurement card being asked to
  carry a design decision it had no criteria for. The split is the fix; noticing the
  scope drift six reviews in is the lesson.
