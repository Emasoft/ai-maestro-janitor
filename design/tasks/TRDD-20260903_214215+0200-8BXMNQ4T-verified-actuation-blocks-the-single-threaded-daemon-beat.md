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

**VERDICT — the tail BREACHES the ceiling; this card is NOT a comment-and-close.**
The card's own criterion is *"if beats stay on cadence, this card is a comment and
a close; if they stretch toward 60 s, it is urgent."* Median 5 s and p90 15 s are
fine. But **p99 is 78–98 s on all three tasks — past 60 s, not toward it** — and
the max reaches 194 s. Roughly 1 % of beats miss a full cycle. An earlier draft of
this card said "beats stay ON CADENCE" and closed on the median; that conclusion
was drawn by tabling the max and then omitting it from the verdict.

**Still NOT measured: the condition the card is about.** `grep -c 'rotation-esc'`
is **0** — no rotation window has ever occurred on this host, so none of the above
is measured while actuation is verifying against wedged panes. The p99 breach is
therefore a floor, taken with the suspected cause absent. What causes it is
unidentified: the failure paths were checked and ruled out (no
`gh-notify-inbox.failcount`, no `.err.seen`, zero `fetch failed` lines, so
`Task._backoff_penalty` never fired in this window), which leaves a long
foreground chore, machine sleep, or scheduler jitter — undistinguished.

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
      med 5 s / p90 15 s / **p99 78–98 s** (see the measured section above). Fleet size: **9**.
      DURING one: still **zero samples** — `rotation-esc` is 0 on this host, and that is the
      condition the card exists for.
      **The box was briefly ticked `[x]` with this same annotation; that was wrong** and the
      reviewer's argument for reverting it is my own sentence from TRDD-L46IG69Y — *"nothing
      evaluates a condition written as prose."* A future session greps `- [ ]` for open work,
      not the paragraph under it. A tick with a disclaimer is a closed box.
- [ ] A decision is recorded: either "no action, cost is invisible at this fleet size" (and this
      card closes) or a named mechanism with the measurement that justifies it.
      — **OPEN, and the measurement now argues AGAINST the "no action" branch.** p99 exceeds
      the 60 s ceiling on all three tasks, so the card's own urgency trigger is met at the
      tail even with the suspected cause (a rotation window) entirely absent. A mechanism
      cannot be chosen yet because the p99 cause is unidentified — long foreground chore vs
      machine sleep vs jitter are undistinguished. **Next action: attribute the p99 breach**
      (the `task 'X' done in Ns` markers, already in the log, bound each task's own duration
      and should say whether one chore owns the stall).
      This box was also briefly ticked, on a "defer and re-measure" outcome that is neither of
      the two the box enumerates.
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
- **A ticked box with a prose disclaimer is a closed box.** Both acceptance boxes were
  briefly `[x]` with honest annotations explaining they were only partly satisfied. That
  is the same defect corrected one card earlier on TRDD-L46IG69Y, and the argument
  against it is that card's own line: *nothing evaluates a condition written as prose.*
