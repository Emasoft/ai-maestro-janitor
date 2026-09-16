---
trdd-id: 3GF9PSQB
title: A failing daemon task stamps a fresh last-run, so every stamp-keyed watchdog is blind to it
column: complete
created: 2026-08-13T02:11:22+0200
updated: 2026-08-13T03:41:00+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
implementation-commits: [0cc466d2]
external-refs: [TRDD-88ZVEQY7, TRDD-6CRC9SQQ]
---

# A completion stamp written on failure makes a dead chore look perfectly healthy

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Found 2026-08-13 while working TRDD-88ZVEQY7.** Read from source, not inferred:

`scripts/daemon.py::Task.poll_background` reaps a finished detached child like this —

```python
dt_s = int(time.time() - self._child_t0)
self._child = None
state.atomic_write(self.last_run_path, str(int(time.time())))   # <- line 1941, UNCONDITIONAL
if rc != 0:
    fails = self._failcount() + 1
    ...
```

The `last_run` stamp is written **before** the `if rc != 0` branch, so it is written on SUCCESS
and on FAILURE alike. A task that fails on every single run therefore carries a **perpetually
fresh completion stamp**.

## Why that matters

Staleness watchdogs key on exactly that stamp:

  - `lib/daemon_watchdog.emit_if_daemon_stale` — "iff `task_name`'s completion stamp is stale".
  - `lib/claimed_chore_watch.classify` — judges a claimed chore from its completion stamp.
  - `global_state.read_last_run` — the shared reader both use.

So for a consistently-failing task **none of them can ever fire**. The louder the failure, the
fresher the stamp. This is the absence-of-signal-is-not-health class inverted into something
worse: a POSITIVE health signal manufactured by the failure itself.

The `failcount` file and the `FAILED … consecutive=N` log line do record the truth — but nothing
that reports health reads them, and the quarantine backoff only slows the task down, it does not
surface anything.

## Not what bit us in 88ZVEQY7 — this is a latent defect, and that is the point

The 22-day-stale fleet payload initially looked like exactly this bug. It was not: the
ai-maestro server had absorbed the chore and the fresh stamp was honest. The defect above is
real all the same, and it was found only because a wrong hypothesis was chased to the source.
Filed so it is not rediscovered the same expensive way.

## Sketch (decide when picked up)

The stamp answers "when did this task last COMPLETE", and the watchdogs read it as "when did
this task last SUCCEED". Either split the two, or make the reader failure-aware:

  - `last-run.ts` on success only, plus a separate `last-attempt.ts`; or
  - keep the unconditional stamp and have `emit_if_daemon_stale` / `claimed_chore_watch`
    additionally consult `failcount` (non-zero for N consecutive runs ⇒ report as unhealthy
    regardless of stamp freshness).

The second is smaller and preserves the backoff logic's current reads. Prefer whichever keeps
ONE meaning per file — the ambiguity is the bug.

**Check the foreground path too.** `Task.run` has its own `finally:` that stamps; verify whether
it has the same shape before fixing only the background lane (the reachable-from-every-caller
discipline — the exact class that produced seven defects on 2026-08-12).

## Acceptance

- [x] A task that fails every run is reported as unhealthy by the stamp-keyed watchdogs, proven
      by a test that FAILS against today's code — `test_failing_task_is_reported_despite_a_fresh_stamp_and_live_daemon`;
      falsified by disabling the branch (7 run, 2 emission guards failed).
- [x] A task that succeeds is unaffected (no new noise) — pinned separately by
      `test_healthy_task_with_a_fresh_stamp_stays_silent` and
      `test_a_transient_failure_streak_below_quarantine_is_silent`. Both stay green with the
      fix disabled, which is correct: they guard against noise, not for emission.
- [x] Both lanes audited — and NEITHER was already correct. `Task.run:1977` and
      `Task.poll_background:1941` share the identical shape (stamp in `finally`, before the
      failure branch). Nothing to record as already-correct.

## ⏵ STATE — 2026-08-13: shipped at 0cc466d2. Read this before reopening.

**Two blinders, not one.** The refreshed stamp is only half of it: even a stale stamp is
suppressed by the `daemon_is_alive()` gate, and a task that is running-and-failing has a live
daemon by definition. A fix that addressed only the stamp would have stayed silent.

**The stamp was deliberately NOT changed.** `time_until_due()` reads it for SCHEDULING (plus the
backoff penalty), so making it success-only would alter retry semantics for every task. The
ambiguity lived in the READERS, so that is where it was resolved — one meaning per file, as the
sketch asked.

**`QUARANTINE_AFTER_FAILS` is now shared** (`global_state`), imported by the daemon that WRITES
the streak and the watchdog that READS it. The alternative — a second threshold in the watchdog —
would have been two definitions of "unhealthy" drifting apart silently, which is this card's own
defect class.

**KNOWN REMAINING GAP — needs a different owner.** `claimed_chore_watch` judges chores claimed by
the ai-maestro SERVER, which writes those stamps. The failure streak is janitor-private daemon
state and does not exist for a server-owned chore, so the same blind spot persists there and
CANNOT be closed from this side. It needs the server to publish a failure signal. Cross-project ⇒
file an issue on ai-maestro, never an edit. Queued behind the user's GitHub-reply gate.

**Provenance worth keeping:** found while working TRDD-88ZVEQY7 on a hypothesis that turned out to
be WRONG (the fleet payload was stale because the server had absorbed the chore, not because a
task was failing). The defect is real independently. Chasing a wrong hypothesis to the source is
what surfaced it — the watchdog's own `last_run <= 0` comment already stated the stamp is
unconditional and reasoned correctly about ZERO; nobody had followed the same fact to non-zero.
