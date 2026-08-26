---
trdd-id: FB84YUGT
title: the heartbeat went silent for 10h20m on an armed cron and nothing noticed
column: todo
created: 2026-08-23T11:00:52+0200
updated: 2026-08-26T07:44:00+0200
current-owner: janitor-main-session
task-type: bugfix
severity: high
scope: project
approval-tier: 0
release-via: publish
relevant-rules: []
npt: []
eht: []
external-refs: []
implementation-commits: []
---

# The heartbeat went silent for 10h20m on an armed cron, and nothing noticed

## ⏵ STATE — READ THIS FIRST ON RESUME

### ⏵ 2026-08-26 — INVESTIGATED. Hypothesis 2 wins, and the measurement below is WRONG.

The logs on disk did separate them. Three findings, in order of how much they change the card:

**1. There were 24 fires on 2026-08-23, not 10 — and TWO gaps, not one.** Read the whole day
instead of `grep -c` + `head -3`/`tail -3`:

```
gap 10.3 h   00:35:42 → 10:55:32
gap  5.4 h   11:02:32 → 16:25:42     ← never noticed; the original probe could not see it
```

The card spends a long paragraph correctly warning that an elided probe misleads, and was
itself written from one. The `tail -3` adjacency argument held for the 10 h gap, so the
headline conclusion survives — but the second gap was invisible to it, and a second occurrence
is exactly the evidence that decides between the hypotheses.

**2. HYPOTHESIS 2 — the cron was ALIVE and could not fire.** Session `fdde8723` fires on BOTH
sides of BOTH gaps. A `CronCreate` job is session-scoped and in-memory: if it had died, that
session could not fire again without a re-arm, and the card's own record says the 10:55 fire
arrived *only after a human typed into the session*. A dead cron cannot be resurrected by human
input; a SUPPRESSED one fires the moment the REPL can take a turn — which is precisely what the
human's keystroke enabled. Under H1 the cron would have to have died and been re-armed twice in
one day, with no arm record for either.

**3. So the fix is NOT re-arming — it is noticing the suppression.** Nothing on the machine
currently observes `now - last-fire >> cadence`. That detector is the deliverable, and it is
worth more than this card: the same blindness covers every "the next heartbeat will handle it"
guarantee, and `heartbeat-fires.log` already carries the data it needs.

**NEXT ACTION:** build the stall detector against `heartbeat-fires.log` (per-session last-fire
vs cadence). It must survive the thing it watches — a detector reached only FROM a fire cannot
report that fires stopped, so it needs a caller that is not the heartbeat (the daemon).

### Original STATE (2026-08-23 — retained; its measurement is superseded by the above)

**Not started.** Filed 2026-08-23 as a by-product of TRDD-5RXBI65T's forensics — surfaced while
settling a different question, so it has evidence but no investigation behind it yet.

**NEXT ACTION:** decide whether the gap was the cron dying or the session being unable to take a
turn (see the two hypotheses below); they need different fixes and the logs already on disk
should separate them.

## The measurement

`.janitor/logs/heartbeat-fires.log`, 2026-08-23 — **10 fires all day**. The probe was
`grep -c` plus `head -3` and `tail -3`, so **only 6 of the 10 lines were ever printed** and the
rendering below marks the 4 that were not:

```
[00:00:37] [s:9248f90c]   [00:05:20] [s:9248f90c]   [00:10:04] [s:9248f90c]     ← head -3 (#1-3)
                    … 4 fires ELIDED, never printed (#4-7) …
[00:33:54] [s:9248f90c]   [00:35:42] [s:fdde8723]   …NOTHING…   [10:55:32]      ← tail -3 (#8-10)
```

**The elided 4 do not weaken the gap, and the arithmetic says where they are.** `tail -3` returns
matches #8/#9/#10, so on an append-ordered log nothing can lie between `00:35:42` (#9) and
`10:55:32` (#10) — the gap is bounded by adjacency, not by inspection. The unseen #4-#7 are
necessarily inside `00:10:04`–`00:33:54`, and four fires at `*/5` (≈00:15/20/25/30) fill that
window exactly. Marked explicitly because a reader of the un-annotated version counts the
`00:10→00:33` jump as a *second* gap that does not exist — and a card arguing against
under-measured data is the worst possible place to elide silently.

The cron was armed at `00:35` (this session, `arm_record.py` wrote `heartbeat-cron-id.txt` +
`heartbeat-armed-at.ts`) at cadence `*/5`. Between `00:35:42` and `10:55:32` that is **10h20m
and roughly 124 fires that did not happen**. The `10:55:32` fire is the one that arrived only
after a human typed into the session.

## Why this matters more than it looks

Every janitor guarantee is "the next heartbeat will handle it":

- `/janitor-arm` reports the arm as **persistent**, and SessionStart re-plumbs silently.
- the whole rate-limit auto-resume design rests on a recurring fire being the wake-up trigger —
  the machine-wide record for that (`~/ai-maestro/design/tasks/TRDD-1222f06a-*.md` §9) says
  explicitly that the cron **IS** the wake-up and that without it the session sits forever.
- `dispatch.py`'s idle-clear, the drift detectors, the memory chores and the ticket dispatch are
  all reached only from a fire.

So a silent heartbeat is not a missed chore, it is **every** chore silently not running, with no
surface that says so. The session looks armed the entire time: `armed.flag` is set,
`heartbeat-cron-id.txt` names an id, `/janitor-arm` reported success — and all three remain true
while nothing fires. That is the same shape as the kanban rule's "an untrue column is worse than
an unstarted card": the state asserts activity that is not happening.

## Two hypotheses, which need different fixes

1. **The cron died or was never live.** Scheduled jobs are session-only; the arm's own skill
   documents that a `CronCreate` succeeding while `arm_record.py` fails leaves a live cron under
   an unrecorded id, and the reverse leaves a recorded id naming nothing. If the job was gone,
   the fix is detection: nothing currently notices that `now - last-fire >> cadence`.
2. **The cron was alive but could not fire.** Fires only land when the REPL is idle *and able to
   start a turn*. A rate-limit UI, a stuck turn, or a modal would suppress every fire while the
   job stays scheduled. Then the fix is not re-arming — it is noticing the suppression.

### A contradiction that looked fatal and WASN'T — retired, recorded

An earlier revision of this card carried a blocker here: `idle-clear-fired.ts` = `09:16:06` sits
**inside the gap**, and the ordering seemed to require `dispatch.py:2348` — which runs from a
heartbeat, contradicting the gap and impugning `heartbeat-fires.log` as an instrument. That
would have been load-bearing, so it was written as a pre-build gate.

**It dissolved.** TRDD-5RXBI65T settled it in source: `external_handoff_clear.main()` captures
`now = int(time.time())` at `:390` on ENTRY and passes that same integer down to `_fire(…, now)`
→ `mark_clear_fired(sd, now=now)`. The stamp therefore records the run's **entry** time while
being **written** minutes later, so a stamp inside the gap implies no fire inside the gap. One
`external_handoff_clear` run explains it, `dispatch.py` is not implicated, and
`heartbeat-fires.log` is not impugned.

**The gap stands, and the detector is unblocked.** Kept rather than deleted because the mistake
is the reusable part: a stamped VALUE was read as its WRITE time. Any watchdog built here will be
comparing timestamps from exactly this family of files — so before treating `now - last-stamp` as
elapsed time, check whether the stamp records when the run STARTED or when the file was WRITTEN.
Get that backwards and the detector mismeasures every long-running writer on the machine.

Both hypotheses are distinguishable from data already on disk (`heartbeat-fires.log` gaps vs the OAuth
rotator's `rotator.log`, which recorded `cookie-leg-stuck` ONSET at `09:04:38` and a
`tick-stalled` alert saying rotation "is effectively OFF"). **The rotator alerts overlapping this
window are a strong hint for hypothesis 2 and MUST NOT be treated as proof** — that is the exact
proxy-read failure TRDD-5RXBI65T is about. Correlation in a log is a lead, not a cause.

## Acceptance

- [ ] the gap's cause is established from logs, and the losing hypothesis is recorded as refuted
      rather than dropped
- [ ] a detector fires when `now - last heartbeat fire` exceeds a small multiple of the armed
      cadence — the missing surface, and the part that is worth shipping whichever hypothesis wins
- [ ] that detector is proven to survive the failure it detects (a watchdog that itself only runs
      from the heartbeat cannot report the heartbeat being dead — this is the load-bearing design
      constraint, not an afterthought)
- [ ] `/janitor-arm`'s "persistent" wording is reconciled with what is actually guaranteed

## Notes and lessons learned

[^1]: [id: LESSON-FB84-1, status: active, keywords: heartbeat_silent_for_hours cron_armed_but_never_fires janitor_did_nothing_overnight armed_flag_lies every_chore_stopped_silently, ocd: 2026-08-23, lmd: 2026-08-23]
    DO NOT treat "armed" as evidence the heartbeat is RUNNING, BECAUSE `armed.flag`,
    `heartbeat-cron-id.txt` and a successful `/janitor-arm` all stay true across a 10h silence —
    they record an intent, never an observation. DO read `heartbeat-fires.log` for a recent fire
    when the question is whether the janitor is alive.
