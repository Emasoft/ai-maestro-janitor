---
trdd-id: 8BXMNQ4T
title: verified actuation blocks the single-threaded daemon beat — measure the multiplier before choosing a mechanism
column: backburner
created: 2026-09-03T21:42:15+0200
updated: 2026-09-04T05:12:00+0200
review-after: 2026-10-04
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

## STEP 1 IS TAKEABLE AFTER ALL — via a proxy I first dismissed (2026-09-04)

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

- [x] The measurement from step 1 is recorded here as a number, with the log window it came
      from — beats/minute during a rotation window vs. outside one, and the fleet size.
      — **HALF answered, and the box is ticked on the half that was ANSWERABLE, not on the
      question as written.** OUTSIDE a rotation window: measured (319 `gh-notify-inbox`
      timestamps, `global-state/daemon.log`, 268 KB on this host) — median wait for the next
      beat 5 s, p90 15 s, against a 60 s ceiling. DURING one: **NOT measurable on this host**
      — `grep -c 'rotation-esc'` is **0**, so no such window has ever occurred here. That is a
      property of the host, not a gap I can close by looking harder, and it is the reason for
      `review-after:` below rather than a close.
- [x] A decision is recorded: either "no action, cost is invisible at this fleet size" (and this
      card closes) or a named mechanism with the measurement that justifies it.
      — **DECISION: no action now, and deliberately NOT a close.** The card's own criterion
      ("if beats stay on cadence, this card is a comment and a close") is satisfied for the
      measured condition. But the condition this card was WRITTEN about is the other one —
      panes wedged, actuation verified, during a rotation — and that is exactly the half with
      zero samples. Closing `complete` on the easy half would assert the urgent case was
      checked. So: `column: backburner`, `review-after: 2026-10-04`, which is a snooze that
      self-releases; re-take the measurement then, when `rotation-esc` lines may exist.
- [ ] If a mechanism lands: a test pins the bound, and `oauth-rotator-tick` is shown still
      running on cadence with every pane wedged.

## Notes and lessons learned
