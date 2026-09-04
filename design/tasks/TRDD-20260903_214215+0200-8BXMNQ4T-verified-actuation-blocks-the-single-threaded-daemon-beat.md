---
trdd-id: 8BXMNQ4T
title: verified actuation blocks the single-threaded daemon beat — measure the multiplier before choosing a mechanism
column: todo
created: 2026-09-03T21:42:15+0200
updated: 2026-09-04T05:34:00+0200
current-owner: janitor-main-session
task-type: refactor
priority: high
severity: medium
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [daemon, pane-state, performance, session-liveness, oauth-rotator]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
created-by: TRDD-N954KWUC P3 follow-up (advisor + review-fork finding, 2026-09-03)
---

# Verified actuation blocks the single-threaded daemon beat

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03

- **NOT STARTED.** Nothing is broken today that anyone has observed; this card exists because a
  cost was introduced knowingly and its size was never measured.
- **NEXT ACTION** — the measurement below, step 1. It is a read of data already on disk. **Do
  not choose a mechanism before it.**
- **SUPERSEDED — do NOT carry forward** — none.

## What changed and why it costs

TRDD-N954KWUC P3 made every janitor keystroke go through read → decide → type → **verify by
re-reading**. The verification is the point of the card: typing blind is what produced the
2026-09-02 incident.

But the pre-P3 baseline was genuinely free. `fleet_inject.fire` spawns the four keystroke
channels (iterm / tmux / wtype / xdotool) with `subprocess.Popen(..., start_new_session=True)`
and never waits — its own docstring says the detachment exists "so the daemon never blocks and
is never killed by the very ESC the plan sends". Only the `aimaestro` channel is synchronous,
and it is an RPC with a meaningful exit code.

So P3 did not make *typing* block. It added **reads** to a loop that previously had none:

- `pane_policy.execute` re-reads after every press, and once more while it waits for the last
  press to take.
- `pane_actuate._read` does `time.sleep(_SETTLE_S)` (3.0 s) before each read so a real terminal
  can repaint.
- The loop runs `max(retries, step.repeat_max)` times.

For the rotation flush (`repeat_max = 1 + queued`, `retries = 3`) that is **up to ~9 s per
wedged pane**, synchronously, on the daemon's single-threaded beat. The recovery rung
(`daemon.py` session-liveness ladder) and fleet-stop pay the same shape.

## Why this is not obviously urgent, and not obviously fine

The failure mode, if it exists, is starvation: a weekly wall wedges *every* pane at once, so
the cost is `panes × ~9 s` in one beat, during which nothing else on the beat runs — including
`task_oauth_rotator_tick`, whose interval is `_INTERVAL_OAUTH_TICK = 60`. That is the task that
rotates *out* of the wall. A guardian that starves its own recovery during the exact event it
exists for would be a serious bug.

**But the multiplier is unmeasured.** On a 1-2 pane fleet, 9 s is invisible and this card is
noise. On a 20-pane fleet it is a real stall. Nobody has counted the panes.

Two reviewers rated this finding on the strength of a baseline claim ("`fire` was detached")
that neither had read at the time. The claim turned out to be TRUE — but it was still an
unread claim, and the *severity* rests on a second number nobody has looked up at all. Picking
a mechanism before knowing which failure it must prevent is the wrong order, and it is how a
plugin option nobody needs gets shipped.

## Plan

1. **MEASURE FIRST — no experiment required, the data is already on disk.** Read the
   beat-to-beat wall-clock deltas in
   `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/daemon.log`
   across a rotation window (a window where `rotation-esc:` lines appear), and compare them to
   the beat interval and to `_INTERVAL_OAUTH_TICK`. Also count the instances a real
   `gather_fleet` returns on this host. If beats stay on cadence, this card is a comment and a
   close; if they stretch toward 60 s, it is urgent.
2. **Only then choose.** Options, cheapest first — the right one depends entirely on step 1:
   - **Spend fewer reads.** The loop keeps re-reading after the press budget is exhausted; the
     final iteration types nothing and still sleeps. Bounding that is a small change inside
     `execute` and is behaviour-preserving for every step whose `repeat_max` is 1. It costs
     patience for the decisive press, which is a real trade, not a free win.
   - **Make `settle_s` a plugin option.** Smallest surface, but it moves the decision to the
     user rather than removing the risk.
   - **Move actuation off the beat.** Correct in the large, biggest change, and only justified
     if step 1 shows real starvation.
   - **A wall-clock cap per beat is a trap**: it makes a pane's press count depend on how many
     panes preceded it, so pane 9 behaves differently from pane 1 for reasons invisible in its
     own log line. Do not take this one without a strong reason.

## STEP 1 — MEASURED, from the right instrument, on the third attempt (2026-09-04)

**Read this section; the two below it are wrong and are kept only as the lesson.**

**The instrument.** The daemon emits a per-task marker for EVERY task —
`[<iso>] task '<name>' starting` and `task '<name>' done in Ns`
(`state.log_line` at the Task dispatch site). Both earlier attempts missed this
entirely: they grepped the chore's own `published …` line and concluded from its
absence that "the daemon emits no per-iteration marker; every logged prefix is a
CHORE". That was false, and it is why both earlier sections are wrong.

The `starting` marker is the correct one: it is emitted BEFORE the task body, so
its start-to-start delta carries no body duration. The `published` line used in
attempt 2 is emitted AFTER an HTTP round-trip, so every delta there was inflated
by API latency — a defect the reviewer predicted before I confirmed it in source.

**Three independent tasks with `interval = 60` (`fleet-stop`,
`oauth-rotator-tick`, `gh-notify-inbox`), same log window
`2026-09-03T22:32:05+0200 → 2026-09-04T04:53:54+0200` (6 h 22 m), fleet size 9
projects** (`gh-issues-monitor/` project dirs). `delta − 60` = wait for the next
beat.

| task | n | med | p90 | **p99** | max |
|---|---|---|---|---|---|
| `fleet-stop` | 336 | 5 s | 15 s | **78 s** | 94 s |
| `oauth-rotator-tick` | 332 | 6 s | 15 s | **98 s** | 194 s |
| `gh-notify-inbox` | 332 | 5 s | 15 s | **80 s** | 185 s |

Three tasks agree to within 1 s at the median and exactly at p90, which is what
makes this a beat measurement rather than three chore measurements.

**CORRECTION to the table above (applied after a review).** `starting` is emitted
before the body, but eligibility is computed from `last-run.ts`, which is stamped
AFTER the body returns. So `delta = 60 + body(n) + wait`, and `delta − 60` is an
upper bound, not the wait. `task 'X' done in Ns` IS `body(n)` and is in the same
log, so the correction is one subtraction:

| task | n | med | p90 | max |
|---|---|---|---|---|
| `fleet-stop` | 339 | 5 s | 15 s | 94 s |
| `oauth-rotator-tick` | 335 | 4 s | 12 s | 187 s |
| `gh-notify-inbox` | 335 | 4 s | 15 s | 184 s |

Bodies are small at the median, so the correction moves med 5→4 s and p90 15→12 s.
**Use this table, not the one above it.**

**STALLED BEATS: 12 stall events across 3 tasks, out of 1048 task-beats (1.1%).**
Numbers below come from ONE snapshot of `daemon.log` copied before analysis. An
earlier draft mixed three snapshots taken ~10 min apart (the log is live and grew
~8 beats between them) and reported the rate to two significant figures anyway.
A stall is `wait > 60 s` — one full cycle skipped, which is the only non-arbitrary
line here (median wait is 4–5 s, so the loop is *always* slightly late). Per task:
`fleet-stop` 5 of 345, `oauth-rotator-tick` 4 of 341, `gh-notify-inbox` 3 of 341.
An earlier draft said "9 distinct minutes / ~339 beats = 2.7%", which divided a
cross-task deduplicated numerator by a single task's denominator.

**The instants below are the DELAYED START — when the stall ended.** An earlier
draft labelled each stall with the *preceding* run's start, which is `60 + body +
wait` seconds too early, and then built a causal story on those wrong times.

**CAUSE — CUMULATIVE foreground occupancy, not "one long body".** The previous
draft matched each stall to the nearest body >60 s and called all 12 explained.
That was post-hoc: only 7 foreground bodies >60 s exist in the window, so with 12
stalls every one was guaranteed a neighbour. Redone properly — for each stall,
sum EVERY foreground body (any duration) overlapping `[eligible, resumed)`:

| task | resumed | wait | covered | by |
|---|---|---|---|---|
| `gh-notify-inbox` | 23:06:56 | 89 s | **98%** | session-liveness 78 + cold-cache-clear 9 |
| `fleet-stop` | 03:51:47 | 67 s | **97%** | oauth-rotator-tick 52 + memory-guard 11 + session-liveness 2 |
| `fleet-stop` | 23:06:47 | 94 s | **95%** | session-liveness 78 + memory-guard 11 |
| `fleet-stop` | 04:34:06 | 78 s | **94%** | session-liveness 73 |
| `oauth-rotator-tick` | 04:48:43 | 108 s | **94%** | session-liveness 53 + gh-notify-inbox 48 |
| `gh-notify-inbox` | 04:35:46 | 150 s | **93%** | cold-cache-clear 94 + session-liveness 45 |
| `oauth-rotator-tick` | 23:07:02 | 97 s | **93%** | session-liveness 78 + 3 others |
| `oauth-rotator-tick` | 04:35:54 | 187 s | **90%** | cold-cache-clear 94 + session-liveness 74 |
| `fleet-stop` | 04:20:24 | 94 s | **87%** | gh-notify-inbox 46 + 3 others |
| `oauth-rotator-tick` | 04:20:11 | 145 s | **86%** | gh-notify-inbox 70 + cold-cache-clear 30 + supervisor 24 |
| `fleet-stop` | 04:17:50 | 90 s | **78%** | session-liveness 55 + oauth-rotator-tick 15 |
| `gh-notify-inbox` | 04:18:26 | 184 s | **54%** | session-liveness 55 + cold-cache-clear 30 + oauth 15 |

**Median coverage 93%; 11 of 12 at or above 78%; one row at 54%.** Contributors are
mostly **sub-60 s bodies stacking** — `fleet-stop`'s 04:17:50 stall is 55 s + 15 s,
neither of which is a "long body". So a per-body deadline below 60 s would NOT have
prevented these; the quantity that matters is total foreground work per beat.

**THE CONTROL — this is what makes the 93% mean something.** Coverage would be a
worthless metric if a normal beat were also ~90% covered (the loop is always doing
*something*). Measured across every wait in the same snapshot:

| wait size | n | median | mean |
|---|---|---|---|
| normal ≤15 s | 884 | **0.0%** | 17.2% |
| mid 15–60 s | 73 | 12.5% | 34.7% |
| **stall >60 s** | **12** | **92.7%** | 88.1% |

Both statistics are shown deliberately: an earlier draft printed the median column
only, which is the more favourable one for normal beats (0.0% vs 17.2%). The
gradient survives either way.

**What this does and does not establish.** On a single-threaded loop "waited long"
and "the loop was busy" are near-definitional, so the control does NOT independently
prove causation. What it does is **exclude every rival hypothesis as a class** —
machine sleep, scheduler jitter, backoff miscomputation, orphaned-run artifacts all
predict LOW coverage on stalls, and stalls measure 92.7%. That is the honest claim;
an earlier draft said the control shows occupancy "discriminates rather than merely
describes", which overstates it.

**The bucketing bias runs AGAINST the finding**, which is what makes it credible:
coverage is `min(c,w)/w`, so a 5 s window needs only 5 body-seconds to reach 100%
while a 184 s window needs 184. Short windows are mechanically *easier* to saturate
and still measure 0.0%.

**Caveat on independence:** the 12 rows are not 12 independent confirmations.
`session-liveness` appears in 8 of them, so one body legitimately delays three tasks
and is counted in three rows — correct physics, but the effective sample is ~5
distinct blocking episodes viewed 12 times.

**The unexplained mass is CLUSTERED, not a lone outlier.** The 54% row (184 s, the
second-largest wait) and the 78% row sit adjacent at 04:17:50 and 04:18:26, while
the 04:34–04:35 cluster runs 90–94%. So ~84 s of unaccounted loop occupancy
concentrates in one ~3-minute window at 04:15–04:18. Cause unknown — and it is the
same window the withdrawn host-load story was reaching for. That story was wrong on
its evidence (it cited events postdating the stalls); the clustering it noticed is
real and is currently explained by nothing.

**Two rows the previous draft got wrong**, both found by review and confirmed here:
`github-config-audit` is a **BACKGROUND** task (`starting (background pid …)`), so it
can never block the loop — listing it as a blocker was wrong twice over, and it also
ended 4 minutes before the task it was credited with delaying became eligible. And
`gh-notify-inbox`'s 70 s body was credited with the stall that IS that same run —
circular. Its legitimate contributions are to OTHER tasks (46 s and 70 s above).

**Bulk lane: EXCLUDED — structurally, which is the argument that actually holds.**
A `background=True` task runs in a detached `subprocess.Popen` child and
`time_until_due()` returns `_BULK_RECHECK_SEC` while that child is unreaped, so it
cannot occupy the loop by construction. The previous draft argued this from the log
instead (four `marketplace-refresh` bodies of ~100 s with no nearby stall) — but
three of those four fall inside a 4 h 44 m stretch with no stalls from any cause, so
the effective sample was ~1. The structural fact was available and unused.
**Unexamined confound:** `marketplace-refresh` pid 3276 ran 22:47:40 → SIGKILLed
23:19:41 (1935 s, workload cap), and the 23:06–23:07 triple falls inside its
lifetime. A detached child cannot block the loop, but it can starve it of CPU — so
why `session-liveness` needed 78 s there is not established.

**Machine sleep: excluded above 94 s only.** The largest gap between any two
consecutive daemon events in 6 h 22 m is **94 s** — and it is exactly
`cold-cache-clear`'s body, i.e. not silence at all. A sleeping machine logs nothing,
so any sleep >94 s is excluded by direct observation. Shorter sleeps are untested;
they are also unnecessary, since all 12 stalls are positively attributed. An earlier
draft argued this from cross-task non-coincidence, which has **no power** below
~120 s: a 90 s sleep delays all three tasks but pushes only those with <30 s to
spare past the 60 s line, producing exactly the one- and two-task pattern observed.

**Waits >94 s require ACCUMULATION, not one long body.** Max inter-event gap is
94 s, yet waits reach 187 s — so no single body explains the worst ones.
`oauth-rotator-tick`'s 187 s spans TWO consecutive long foreground bodies:
`session-liveness` 78 s (ends 04:34:04) then `cold-cache-clear` 94 s (ends
04:35:46). The mechanism is a run of blocking bodies, not one.

**VERDICT — the card's thesis is CONFIRMED in its general form, and SHARPENED.**
Foreground work occupying the single-threaded loop for longer than the 60 s
interval skips a beat; 12 such skips in 6 h 22 m, median 93% accounted for by
summing the foreground bodies in each stall's own window. The contributors are
`session-liveness` (78 s max, appears in 8 of 12 rows), `cold-cache-clear` (94 s),
`gh-notify-inbox` (70 s), `oauth-rotator-tick`, `memory-guard`,
`oauth-rotator-supervisor` — **all pane- or session-touching, which is the family
this card suspects, and none is rotation actuation.** Median 4–5 s and p90 12–15 s
are healthy; the damage is confined to the tail.

**What is NOT established:** the 54% row (184 s, only 100 s accounted for), why
`session-liveness` took 78 s at all, and whether the loop dispatches due tasks in
registration order — which would explain why `fleet-stop`, whose own body is always
0 s, stalls most often (it is registered immediately after `session-liveness`, the
most frequent contributor). That last one is a hypothesis from the `started
(pid=…, tasks=[…])` ordering, not a reading of the dispatch code.

**Still ZERO samples of the condition the card exists for.** `grep -c 'rotation-esc'`
is **0** — nothing above was measured while actuation verifies against wedged panes.
The mechanism is now demonstrated, so a rotation window would add load to a loop
already shown to skip beats under it; that is an inference, not a measurement.

**Fleet: 15 projects with a `.janitor/state/armed-cadence.cron`** — one file each,
so no double-count. **That file is the last ARM RECORD, not proof of current
arming** (`armed.flag` lives in the control dir; `find ~/.claude/projects -name
armed.flag` returned 0). Two earlier figures were worse: **9** counted cumulative
`gh-issues-monitor/` registry dirs, and the `Task` docstring's **40** is a
2026-07-17 incident figure.

## (SUPERSEDED — both numbers and premise wrong) attempt 2, via the published-line proxy

I wrote the section below concluding the measurement was impossible. A review
asked whether `gh-notify-inbox` (316 lines) might itself be a per-beat marker,
and it effectively is. **The card's step 1 is answered.**

**Method.** `_INTERVAL_GH_NOTIFY_INBOX = 60` (`daemon.py:267`), the SAME as the
loop ceiling. So the chore becomes ELIGIBLE 60 s after its last run and fires on
the next beat at-or-after that. Therefore **delta − 60 = the wait for the next
beat**, which is the quantity this card wants.

**Measured** over 319 distinct `gh-notify-inbox` timestamps in
`global-state/daemon.log`:

| | delta | wait for next beat |
|---|---|---|
| min | 60 s | **0 s** |
| p10 | 61 s | 1 s |
| median | 65 s | **5 s** |
| p90 | 75 s | **15 s** |
| max | 384 s | **324 s** |

**Verdict: beats stay ON CADENCE.** The card's own criterion is *"If beats stay
on cadence, this card is a comment and a close; if they stretch toward 60 s, it
is urgent."* At the median a beat arrives 5 s after eligibility and at p90 15 s —
nowhere near 60 s. Verified actuation is NOT visibly blocking the beat at this
fleet size.

**The max (324 s) is NOT evidence against that**, and it should not be read as a
stretched beat: a single 384 s gap is equally explained by the daemon being down,
restarted, or the host asleep, and one observation cannot distinguish those. It
is also 1 of 319. Worth knowing, not worth acting on.

**Caveat that bounds the whole measurement:** this is an UPPER bound on the beat
interval only when a beat actually carries the chore. If the beat were much
FASTER than 60 s the deltas would look identical (~60), so the data cannot
distinguish a 5 s beat from a 55 s one — it only shows the beat is not
STRETCHING, which is precisely the question asked. Do not reuse these numbers as
a beat-interval measurement; they bound the wait, not the period.

## WHY I FIRST SAID IT WAS NOT TAKEABLE — the dismissed-proxy error, kept

The section below is superseded by the measurement above. It is kept because the
error is the reusable part: I checked for a marker NAMED like a beat, found only
chore prefixes, and concluded no beat signal existed — without asking whether a
chore that runs EVERY beat is a beat signal. "A chore that runs every Nth beat
cannot bound the beat" is true and was the wrong question; the right one is
whether any chore has N=1, and `gh-notify-inbox` effectively does.

Two data facts in it remain TRUE and still matter: there are **0 `rotation-esc`
lines**, so the "during a rotation window" half of step 1 is still unmeasurable
here, and the daemon still emits no explicit per-beat line.

## (SUPERSEDED) STEP 1 IS NOT TAKEABLE FROM THIS LOG

Step 1 says "MEASURE FIRST — no experiment required, the data is already on
disk", and asks for beat-to-beat wall-clock deltas across a rotation window.
Neither half of that data exists in
`global-state/daemon.log` (268 KB on this host):

1. **No rotation window.** `grep -c 'rotation-esc'` → **0**. There is no window
   to measure "during" against.
2. **No beat marker, so beat-to-beat deltas are not derivable AT ALL.** The 30
   lines matching `beat` are `session-liveness: … recovery injections deferred
   this beat` — prose, not a per-iteration marker. Confirmed in source: the loop
   at `scripts/daemon.py:463` (`while True:`) emits no `log_line` per iteration;
   every logged prefix is a CHORE (`gh-notify-inbox` 316, `memory-guard` 68,
   `session-liveness` 46, `os-keepalive` 1, `cache-prune` 1). A chore that runs
   every Nth beat cannot bound the beat.

**A wrong number I nearly recorded, kept as the warning.** I first computed
deltas between ALL timestamped lines — n=3932, median 0 s, p90 18 s, max 82 s —
and 82 s exceeding `_INTERVAL_OAUTH_TICK` (60 s, `daemon.py:215`) looks exactly
like the "stretching toward 60 s" this card calls urgent. It is not that
measurement: consecutive lines are mostly WITHIN one beat, which is why the
median is 0. Reporting it would have raised a false alarm on the same defect
this session hit on TRDD-L46IG69Y — measuring an available population instead of
the asked-for one, because it was available.

**What would actually take this measurement:** a per-iteration `log_line` in the
daemon loop (one line, gated behind a debug flag so it does not bloat the log),
then wait for a real rotation window. That is an instrumentation change plus a
wait, not "a read of data already on disk" — so this card's NEXT ACTION is
wrong as written and step 1 needs re-scoping before anyone tries again.

**Not instrumenting it here**, deliberately: adding a log line to the live
machine-wide daemon to satisfy a `medium`-severity card, while an unidentified
test flake from this session is still outstanding, trades a clean attribution
surface for a number nobody is waiting on.

## Acceptance

- [ ] The measurement from step 1 is recorded here as a number, with the log window it came
      from — beats/minute during a rotation window vs. outside one, and the fleet size.
      — **TWO of three delivered; the box stays OPEN on the third.** OUTSIDE a rotation
      window: measured from the per-task `starting` markers, three tasks, 6 h 22 m window,
      med 4–5 s / p90 12–15 s, with **12 stalls in 1048 task-beats (1.1%)**, median **93%**
      of each stall accounted for by summing the foreground bodies in its own window (table
      above). Fleet: **15 projects carrying an arm record** — not the same as currently
      armed, see the section above.
      DURING one: still **zero samples** — `rotation-esc` is 0 on this host. This half is not
      obtainable by looking harder; it needs a rotation to occur.
      **The box was briefly ticked `[x]` with this same annotation; that was wrong** and the
      reviewer's argument for reverting it is my own sentence from TRDD-L46IG69Y — *"nothing
      evaluates a condition written as prose."* A future session greps `- [ ]` for open work,
      not the paragraph under it. A tick with a disclaimer is a closed box.
- [ ] A decision is recorded: either "no action, cost is invisible at this fleet size" (and this
      card closes) or a named mechanism with the measurement that justifies it.
      — **UN-TICKED AGAIN, and this time the reason is that the mechanism I named does not
      follow from the measurement.** I ticked this with "move the four blockers to the bulk
      lane". Three objections, two of which I had written into the same paragraph:
      (a) `task_gh_notify_inbox`'s docstring argues explicitly AGAINST the lane for itself —
      recording that as a caveat *is* an admission the mechanism fails for a quarter of its
      targets; (b) `session-liveness` is the pane-RECOVERY task, the lane SERIALISES, and it
      just demonstrated a 1935 s occupant — moving it risks converting a 78 s beat delay into
      a 20-minute recovery delay, which is the 2026-07-17 starvation incident the lane's own
      docstring exists to record; (c) the lane would gain 4 contenders for one slot with no
      measurement of queueing.
      **And the per-row check killed the obvious alternative too.** "Bound each body below
      60 s" does not follow either: the stalls are built from bodies of 55 + 30 + 15 s —
      individually legal, cumulatively over the interval. The measurement names *total
      foreground occupancy per beat*, and neither candidate remedy addresses that quantity.
      **What the measurement DOES support**, and all this box can honestly carry today:
      `session-liveness` appears in 8 of 12 stall rows and is the single largest contributor.
      Bounding or backgrounding IT alone is the change the data points at — but it is the one
      task where backgrounding is most dangerous, so it needs a design decision, not a move.
      **The advisor must be consulted before any `scripts/daemon.py` scheduling change.**
      **Half of this box CAN be closed now**, and the enumeration is not
      exhaustive-or-nothing: the *"no action, cost is invisible at this fleet size"* branch is
      **definitively ruled out** — 12 stalls, attributed, with a control showing normal beats
      are 0% covered. What remains open is only which remedy, and that is a design question.
      **Ticks 1 and 2 were optimistic; this un-tick is not.** Tick 1 was on "defer and
      re-measure" (not an enumerated option) and tick 2 on a mechanism contradicted inside its
      own box — both lapses. Un-tick 3 followed a *new finding* (cumulative, not single-body)
      that invalidated both candidate remedies, which is evidence changing a decision. An
      earlier draft of this note called all three "optimistic", which was itself a tidy
      summary the detail does not support.
- [ ] If a mechanism lands: a test pins the bound, and `oauth-rotator-tick` is shown still
      running on cadence with every pane wedged.

## Notes and lessons learned

- **Three attempts, and the first two failed the same way: I grepped for the thing I
  expected to be NAMED like a beat, found only chore prefixes, and concluded from that
  absence that no beat marker existed.** It existed the whole time —
  `task '<name>' starting`, emitted for every task on every run. Attempt 1 concluded
  "not measurable"; attempt 2 built a proxy out of the wrong line (`published …`, which
  is emitted after an HTTP call, so every delta was inflated by API latency) and reported
  a median. A grep that returns nothing is evidence about the PATTERN, never about the
  log — and the way to check is to read one raw line, which is what finally did it here.
- **The verdict was reversed by the tail I had tabled and then dropped.** Attempt 2
  printed `max 384 s` in its own table and concluded "beats stay ON CADENCE" from the
  median. The correct instrument gives p99 = 78–98 s against a 60 s ceiling. On a card
  about a TAIL condition (panes wedged during rotation), the tail sample is the
  population of interest, not noise to trim — discarding it silently is how a card about
  rare stalls gets closed on its common case.
- **The generator behind all three failed attempts is ONE habit, and it is not "wrong
  population".** Each attempt stated a claim at higher confidence than the step that
  produced it: attempt 1 read a grep's silence as proof no marker existed; attempt 2
  called `delta − 60` "the wait" when it is `body + wait`, and called three tasks on ONE
  loop "agreeing" as if that were independent corroboration (it is entailed by the shared
  loop and certifies nothing); attempt 3's commit subject attributed the stall to the
  daemon while its own body said the cause was unknown. Wrong-population was one symptom.
  The check that would have caught all three is the same: **before writing a claim, name
  the step that produced it and ask what that step actually establishes.**
- **`f5885338`'s commit message justified the `backburner → todo` revert with "the
  transition matrix lists only the forward direction" — that is argument-from-absence,
  inside the commit that exists to correct argument-from-absence.** The matrix is a
  "Quick reference" of transitions and their side effects and does not claim to be
  exhaustive. The revert is right on other grounds: a measured ceiling breach is not a
  park, and undoing my own unjustified edit needs no transition warrant. Retracted here
  because the commit message cannot be.
- **A ticked box with a prose disclaimer is a closed box.** Both acceptance boxes were
  briefly `[x]` with honest annotations explaining they were only partly satisfied. That
  is the same defect corrected one card earlier on TRDD-L46IG69Y, and the argument
  against it is that card's own line: *nothing evaluates a condition written as prose.*
