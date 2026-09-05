---
trdd-id: QJ5LP4W2
title: bound total foreground occupancy per daemon beat so a run of long bodies cannot skip a cycle
column: todo
created: 2026-09-04T05:29:46+0200
updated: 2026-09-05T07:14:40+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-05

- **BLOCKED ON ACCEPTANCE BOX 1, WHICH IS THIS CARD'S OWN GATE, AND IT IS WORKING AS
  INTENDED.** Box 1 requires the fable advisor before any `scripts/daemon.py` scheduling
  change is *written*. Attempted 2026-09-05: `Agent(subagent_type: "fable-advisor:advisor")`
  → **"Agent type not found"**.
- **CAUSE — diagnosed, single, and NOT a defect:** `~/.claude/settings.json:412` carries
  `"fable-advisor@z13z4ck-plugins": false`. The plugin is installed and COMPLETE (cache
  `z13z4ck-plugins/fable-advisor/{1.4.0,1.5.0,1.6.0,1.6.1}`, and **1.6.1 does ship
  `agents/advisor.md`**) — it is simply DISABLED, so the agent never registers. There is also
  no built-in advisor tool in this session, so **both advisor paths named by the standing rule
  failed**, which that rule requires be stated explicitly rather than silently skipped.
  - *An earlier reading of this — "1.6.1 ships an empty `agents/` dir" — was WRONG*, an `ls`
    misread corrected by `find … -type f | wc -l` = 1 before it reached any commit. Do not
    resurrect it; there is nothing wrong with the install.
- **DO NOT write the scheduling change to satisfy the card without the consult.** This card's
  own box says the rule applies here *"with force, not as a formality"* — a single-threaded
  machine-wide daemon that owns OAuth survival. Enabling the plugin is a change to the USER's
  own `~/.claude/settings.json` and takes effect only after a restart, so it is the USER's
  call, not something to flip mid-session to unblock a chore.
- **NEXT ACTION for the MECHANISM — one of, and it needs the USER:** (a) re-enable
  `fable-advisor` and restart, then run the consult; or (b) the USER waives box 1 for this card.
- **⚠ BUT WORK REMAINS THAT BOX 1 DOES NOT GATE — a first draft of this block said "nothing
  else on the card is startable", which was FALSE and, sitting in a STATE block, would have
  foreclosed it for every later reader.** Box 1 gates *writing a `scripts/daemon.py` scheduling
  change*. It does not gate:
  - **The two open questions below — the FIRST is PARTLY answered (2026-09-05), the second
    is untouched.** On the first, and no stronger than the section it summarises: long
    single bodies are MEASURED (a 78/78/77 s cluster, n=3, plus beats of 102/137/191 s
    across ~32 h of `daemon.log`) — **the measurement is the finding; every attribution of
    it is open.** `probe_iterm_sessions`' escalating ladder (`fleet_scan.py:1234/1237`) is
    the only known mechanism whose ceiling brackets the 78 s, and it is UNCONFIRMED; the
    100 s+ beats exceed its 96 s ceiling and may be a larger single cost OR that ladder plus
    per-instance costs (ZVZAFQY6). Do not re-derive the measurement; do not treat any
    attribution as settled. **STILL OPEN and still ungated:** *what is the ~84 s unaccounted
    at 04:15–04:18?* — now with bigger siblings. Read-only diagnosis; the precedent is set
    here for ungated read-only source reading.
  - **The replay harness for box 3.** Building a test that replays the worst measured occupancy
    pattern is not writing a scheduling change; only the bound it pins is.
  *(A first wording of this bullet added "…more than anything the advisor could say": a
  confident comparative about an advisor nobody has reached, unfalsifiable, and sitting in a
  block that is authoritative by rule.)*
- **⚠ A REFRAMING FOR THE CONSULT — CONDITIONAL, and written BEFORE the advisor was reached.**
  The card was built on "stalls are cumulative across many bodies, so no per-body deadline
  helps". That stands for the 55+15 stall. **Single bodies of 78–191 s are now MEASURED, so
  the claim is not general — but that is all that is established.** Nothing here says a
  per-body deadline is the right mechanism, or that any single CALL dominates those bodies:
  the 78 s attribution is unconfirmed and the 100 s+ beats may themselves be cumulative
  ACROSS INSTANCES inside one body (ZVZAFQY6), which a per-body deadline would truncate
  rather than fix.
  **Give the advisor BOTH framings — the original cumulative one and this one — and the
  measurement; do not hand over only the narrowed question.** This bullet eliminates no
  candidate: 3 and 4 both stand. Choosing between them is the design judgment box 1 reserves.
  *(Written into an authoritative STATE block pre-consult, which is how a framing becomes the
  only framing a later reader sees; flagged here rather than trusted.)*
- **A SEPARATE defect surfaced during this diagnosis and is NOT this card's work:** the
  per-instance path reads the SAME pane up to three times (`daemon.py:1999`, and independent
  `read_pane_text` calls inside `fleet_inject.command_plan_field_busy` at `fleet_inject.py:430`
  and `field_holds_our_queued_command` at `:489`), against a comment at `daemon.py:1995`
  asserting the policy table "costs no extra osascript". Filed as its own card per TRDD clause
  13 rather than absorbed here — this card is a scheduling-bound decision, that one is a
  redundant-IO fix, and merging them would gate a cheap fix behind an advisor consult it does
  not need.
- **The analysis is NOT the blocker — it is done.** Candidates 1 and 2 are rejected with
  reasons, 3 and 4 stand, and the transferable structure (decide the budget/deferral set ONCE
  before the loop) is settled below. The consult is for choosing between 3 and 4 and for
  designing the priority floor, which has no precedent in `daemon.py`.

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

- **Why does `session-liveness` need 78 s at all?** **PARTLY ANSWERED, 2026-09-05 —
  and NOT by the mechanism I first named. Read the correction; the first version of
  this entry is wrong in a way worth keeping.**

  **THE CANDIDATE, from source.** `task_session_liveness` (`daemon.py:1544`) calls
  `fleet_scan.gather_fleet` once (`daemon.py:1593`), which calls
  `probe_iterm_sessions` once (`fleet_scan.py:1417`), gated only on `iterm_running`
  (`:1413`). That probe retries the iTerm enumeration **three times with ESCALATING
  deadlines — `_ITERM_PROBE_TIMEOUTS = (15.0, 30.0, 45.0)` (`fleet_scan.py:1234`)
  plus `_ITERM_PROBE_BACKOFF_S = (2.0, 4.0)` (`:1237`)** — 51 s for two exhausted
  attempts and backoff, 96 s for full exhaustion. The ladder was deliberate
  (2026-08-28, contention not denial); nobody costed it against the 60 s beat.

  **⚠ I FIRST WROTE THAT THIS *IS* THE 78 s, on the strength of 15+2+30+4+≈27 ≈ 78.
  That was an arithmetic FIT presented as a finding — the 27 is not measured, it is
  whatever residual makes the sum land on the number, and ANY ladder with a ceiling
  above 78 admits such a fit.** Recorded rather than deleted because it shipped into
  a STATE block, which is authoritative by rule: the failure mode is not the wrong
  guess, it is that a fit written there is indistinguishable from an observation.

  **THE ACTUAL MEASUREMENT** (`global-state/daemon.log` + `.log.1`, 2026-09-03T22:32
  → 2026-09-05T06:57, ~32 h, every `task 'session-liveness' done in Ns` line):

  - **The body is cheap almost always:** 375 beats at 2 s, 194 at 3 s, 84 at 4 s.
    The long beats are rare and episodic, not a standing cost.
  - **A tight cluster at the top: 78 s, 78 s, 77 s** (2026-09-03T23:06,
    2026-09-04T04:34, 04:47). Three long beats within 1 s of each other suggests a
    BOUNDED cost rather than an unbounded one — the best evidence here for a fixed
    component, **and n=3.** It does not identify WHICH bound: a fixed remote timeout,
    a lock held for a bounded period, or a retry ladder all cluster this way.
  - **But beats of 102 s, 137 s and 191 s also occur** (2026-09-04T15:36, 21:49,
    17:18). **Those EXCEED the ladder's 96 s ceiling, so the ladder cannot be the
    whole cost of those beats.** Two shapes fit, and the second needs no new
    mechanism: (a) a larger single unidentified cost, or (b) **the ladder ADDING to
    per-instance costs — see TRDD-ZVZAFQY6, up to ~45 s per instance on osascript,
    additive because the loop is a plain `for`. Two instances on that path plus a
    full ladder reaches 191 s with nothing new invoked.** Do not go looking only for
    a single ~191 s thing.

  **So the honest status:** a bounded ~78 s component is real and the ladder is the only
  known mechanism on this path whose ceiling brackets it; the attribution is
  UNCONFIRMED, and the 100 s+ beats are unexplained by it either way.

  **WHAT WOULD SETTLE IT, so this is a takeable task and not a re-litigation:** a
  timestamp either side of the `probe_iterm_sessions` call in `gather_fleet`
  (`fleet_scan.py:1417`), logged unconditionally, answers it in one long beat. The
  attempt count already exists in that scope — logging `osascript_attempts`
  unconditionally rather than only inside the `blocked` suffix would do it too.

  **THE FALSIFIER THAT DOES NOT WORK — do not run it and read silence as
  confirmation.** The obvious check is `gather_fleet`'s attempt count, which suffixes
  the outcome `(after N attempts)` when N>1. It only fires when `probe_outcome` is
  non-empty (`fleet_scan.py:1439`), and `probe_outcome` is `""` unless `blocked`
  (iTerm up AND zero sessions enumerated). **A probe that retries and then SUCCEEDS
  leaves no trace at all** — and indeed the ~32 h of logs contain zero such suffixes,
  which refutes nothing. Confirming the ladder needs a timestamp around the probe,
  i.e. an instrumentation change, not a log read.

  **What this does NOT establish:** it says nothing about the typical body, nothing
  about the ~84 s unaccounted below, and the detached-bulk-child CPU-starvation
  confound named by the original question is untested and stays open.

  Inventory of every blocking call on the path, with timeouts and per-beat vs
  per-instance attribution: `reports/qj5lp4w2-session-liveness/20260905_120000+0200-session-liveness-blocking-inventory.md`
  (gitignored). Its two load-bearing claims were re-verified against source before
  being written here; two call sites in it are marked UNDETERMINED and were not
  traced (`_rotation_esc_pass` `daemon.py:2195`, `_resume_wake_pass` `:2307`).
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

  **⚠ FOURTH attempt at this paragraph, and the THIRD wrong mechanism — the prose above
  states the underdetermination correctly and then a table smuggled a mechanism back
  in.** The retracted table had two rows: *"selects who RUNS → never selected →
  **starved**"* and *"selects who is DEFERRED → never deferred → **protected**"*. **Row
  2 holds. Row 1 is false**, and the dispatch loop refutes it:

  ```python
  if task.background:
      if bulk_busy or task is not bulk_next:
          continue          # one bulk lane: defer
      task.spawn_background()
      continue
  task.run()                # foreground: unconditional
  ```

  `bulk_next` gates **only** the `task.background` branch; a foreground task reaches
  `task.run()` regardless. "Never selected" therefore means *nothing* for a foreground
  task — that selection is not what decides whether it runs.

  **And row 1 is not even a readable alternative.** The lane's rule is a **scarcity
  allocator**: one lane, N due background tasks, pick one. The foreground loop has no
  scarcity — *every* due foreground task runs, every pass. To port the rule as "who
  runs" you must FIRST invent a foreground scarcity constraint that does not exist
  today, and the starvation outcome would then follow from that invented constraint,
  not from `min(due, key=_last_run)`. Presenting the two rows as symmetric made the
  underdetermination look like a live 50/50 when only one row describes a policy anyone
  would write here.

  **So the polarity point stands, but only in one direction, and the honest form is
  simply: the port's semantics are unspecified and nothing about the survival beat
  follows from them.** Attempt 1 was a category error (`t.background` filters the beat
  out entirely), attempt 2 an inversion, attempt 3 this table. Each was presented as
  the sober correction of the last.

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

**⚠ Correcting a claim in `4453f8b4`'s own commit message.** It says *"the mechanical
corrections this session have all been right; **every** interpretive rewrite has
failed."* Both halves are one notch too wide — the same defect the sentence was
describing:

- **"Every interpretive rewrite has failed" is refuted by the commit it appears in.**
  The candidate-framing rewrite in `4453f8b4` is interpretive and it held. So is
  `TRDD-3BQM5GH7`'s central narrative ("the ignore file is for a tool we do not run"),
  which has survived every round since. The true claim is much narrower and still
  striking: **every attempt to state a concrete mechanism for the `_next_bulk_task`
  port has failed — four for four.**
- **"The mechanical corrections have all been right" glosses one.** `_run_due_pass` was
  an invented symbol — a mechanical error — and it landed in `738e5f67`. I caught it
  myself before review, which is not the same as it never happening.

**The lesson underneath is about the SHAPE of the failures, not their count.** The
paragraph that kept failing is the one asking *"what would this policy do to a specific
task?"* — a question the evidence cannot answer, because the policy does not exist yet.
Each rewrite invented a slightly different policy in order to have something concrete to
say about it. **When a question presupposes an artifact that has not been designed, the
answer is not a better guess; it is naming the missing artifact.**

- **A card whose title says "measure X" should not be the card that decides how to
  fix X.** 8BXMNQ4T's remedy box was ticked and un-ticked three times, and at least
  the last of those was not optimism — it was a measurement card being asked to
  carry a design decision it had no criteria for. The split is the fix; noticing the
  scope drift six reviews in is the lesson.
