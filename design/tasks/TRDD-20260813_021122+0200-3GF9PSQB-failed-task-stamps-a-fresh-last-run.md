---
trdd-id: 3GF9PSQB
title: A failing daemon task stamps a fresh last-run, so every stamp-keyed watchdog is blind to it
column: todo
created: 2026-08-13T02:11:22+0200
updated: 2026-08-13T02:11:22+0200
current-owner: unassigned
task-type: bugfix
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
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

- [ ] A task that fails every run is reported as unhealthy by the stamp-keyed watchdogs, proven
      by a test that FAILS against today's code
- [ ] A task that succeeds is unaffected (no new noise) — pinned separately
- [ ] Both the background (`poll_background`) and foreground (`run`) lanes audited, and whichever
      is not changed is explicitly recorded as already-correct
