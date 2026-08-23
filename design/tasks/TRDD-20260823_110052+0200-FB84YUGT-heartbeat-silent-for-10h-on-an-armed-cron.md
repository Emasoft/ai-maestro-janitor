---
trdd-id: FB84YUGT
title: the heartbeat went silent for 10h20m on an armed cron and nothing noticed
column: todo
created: 2026-08-23T11:00:52+0200
updated: 2026-08-23T11:00:52+0200
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

**Not started.** Filed 2026-08-23 as a by-product of TRDD-5RXBI65T's forensics — surfaced while
settling a different question, so it has evidence but no investigation behind it yet.

**NEXT ACTION:** decide whether the gap was the cron dying or the session being unable to take a
turn (see the two hypotheses below); they need different fixes and the logs already on disk
should separate them.

## The measurement

`.janitor/logs/heartbeat-fires.log`, 2026-08-23 — **10 fires all day**:

```
[00:00:37] [s:9248f90c]   [00:05:20] [s:9248f90c]   [00:10:04] [s:9248f90c]
[00:33:54] [s:9248f90c]   [00:35:42] [s:fdde8723]   …then NOTHING…   [10:55:32] [s:fdde8723]
```

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

Both are distinguishable from data already on disk (`heartbeat-fires.log` gaps vs the OAuth
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
