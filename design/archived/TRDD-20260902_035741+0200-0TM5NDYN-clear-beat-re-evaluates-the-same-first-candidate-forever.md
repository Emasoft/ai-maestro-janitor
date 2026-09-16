---
trdd-id: 0TM5NDYN
title: The clear beat re-evaluates the same first fleet candidate every beat, so a HOLD on candidate one starves every other session
column: complete
created: 2026-09-02T03:57:41+0200
updated: 2026-09-02T04:40:00+0200
current-owner: janitor-main-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
severity: high
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-O7UCNNN2, TRDD-PXP08ZQC, TRDD-1QJIZFFW]
implementation-commits: [6a3605b4]
---

# One candidate per beat is right; the SAME candidate every beat is not

## Measured 2026-09-02 03:57 (not inferred)

- First live beat after TRDD-O7UCNNN2 (03:53:09): the lane evaluated this repo — first in
  fleet order — and the watcher answered `VERDICT HOLD why=active-waiting`. A HOLD writes
  no cooldown stamp (`clear_in_cooldown` fires only after a CLEAR), so the next beat walks
  the fleet in the same order, reaches the same first root, spawns the watcher again, HOLDs
  again, and `return 0  # one per beat` (`cold_cache_clear_task.py:204`) ends the beat.
- Meanwhile three other sessions are ABOVE the 300k floor right now (statusline: 533.9k,
  412.1k, 336.2k) and are never reached: the one-per-beat rule, meant to bound concurrent
  watchers, has become "one ROOT per machine".

## Fix (smallest correct shape)

Stamp `<root>/.janitor/state/clear-evaluated.ts` (epoch) when the watcher is spawned for a
root, and skip a root whose stamp is younger than `CLEAR_EVAL_SPACING_S` (default 900 s,
env `CLAUDE_PLUGIN_OPTION_IDLE_CLEAR_EVAL_SPACING_SECONDS`, read via `state.plugin_option`)
in the same loop that skips cooldown — count it as its own skip reason (`recent`) in the
no-candidate summary line. The beat then walks the whole fleet over successive beats with
still at most one watcher per beat; a root that HOLDs is retried every 15 min, not every 5,
which is also cheaper. A CLEAR still writes the cooldown stamp as today — the two stamps
are different facts (evaluated vs cleared), so two files, per the COQN6KVA lesson.

## Acceptance

- [x] a root evaluated `< spacing` ago is skipped and counted as `recent`; a root evaluated
      `>= spacing` ago is eligible again; the stamp is written at spawn, before the watcher's
      verdict is known — three tests in `tests/test_daemon_cold_cache_clear.py` (two beats
      evaluate two different roots; `recent=1` in the summary; an old stamp re-qualifies)
- [x] a CLEAR still lands the cooldown stamp; `clear_in_cooldown` untouched (existing tests)
- [x] ruff clean, `mypy scripts/` clean (497 files), 47 tests in the three files green —
      re-run by the approver after the worker's report
- [x] after publish + restage — OBSERVED: daemon respawned on 3.4.7 at 04:31:04 (pid 53070,
      staged `cold_cache_compact.py` == cache); beat 04:33:53 evaluated this repo, beat
      04:39:00 evaluated AgentlensPro — two different roots in two CONSECUTIVE beats — and
      `clear-evaluated.ts` exists under both roots' `.janitor/state/`

## Approval log

- 2026-09-02T04:40:00+0200 — COMPLETE, closed under the USER's delegated review authority
  ("i've put you in charge", 2026-09-01). Shipped in 3.4.7 (6a3605b4); the closing box is
  the restaged daemon's own log. Self-closure disclosed.

## Notes and lessons learned

- "One per beat" bounded concurrency; nobody asked which one. Any per-beat limiter needs a
  rotation rule or it degenerates to a fixed pick.
