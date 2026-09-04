---
trdd-id: 2640RYR5
title: the cadence measured a directive's mtime against the caller's stale now sample
column: dev
created: 2026-09-05T00:56:33+0200
updated: 2026-09-05T00:56:33+0200
current-owner: main-session
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
relevant-rules: []
npt: []
eht: []
blocked-by: []
implementation-commits: []
---

# `_cadence_active_waiting` compared a filesystem mtime to the caller's clock frame

## The symptom, and how it surfaced

`tests/test_dispatch_cadence.py::test_active_waiting_non_ratelimit_reasons_stay_true_without_coverage`
failed in a full-suite run (**1 failed, 16413 passed, 1 skipped, 12m09s**) and passed
standalone in 2 s. Its module alone passed; the module plus the newest test file passed.
Collection order is deterministic (no `pytest-randomly` installed), and the module passed
alone and paired — the clock explanation below accounts for the failure without a polluter.

## The bug

`_cadence_active_waiting(sd, now)` answers *"is this session waiting on something RIGHT
NOW"*. `now` is sampled by the CALLER at the top of a fire and passed down. The directive
branch did:

```python
age = now - int(directive.stat().st_mtime)
if 0 <= age < _RESUME_RECENCY_WINDOW_S:
```

**Two different clock frames, compared as if they were one.** The sibling branch above it
compares `now` against a RECORDED STAMP (`state.read_int_state`) — same frame, correct.
This one compares it against a FILESYSTEM MTIME, which belongs to the real clock, not to
the caller's sample. A directive written any time AFTER `now` was sampled is *fresher than
`now` knows*, so `age` goes negative and `0 <=` rejects it: **the freshest possible signal
reported "not waiting"**, falling through to a weaker probe.

In the test, `now` was sampled at line 266 and the write landed at line 269. A 12-minute
suite under load crosses a wall-clock second there; a 2-second standalone run does not. The
same gap exists for any fire slow enough between its sample and this check, and the
idle-compact / idle-clear phases this gates would then shrink or clear a context a resume is
about to need. (Measured in the test; not observed in production.)

## The fix

Measure the mtime against `time.time()` at check time:

```python
age = time.time() - directive.stat().st_mtime
if 0 <= age < _RESUME_RECENCY_WINDOW_S:
```

A file written BEFORE this check cannot be in its future, so `0 <=` is correct again with no
tolerance to justify. Dropping `int()` also removes a truncation that widened the window.
The docstring now says `now` governs the stamp comparisons only.

## Two rejected fixes, recorded so they are not re-litigated

**A future tolerance (`-5 <= age`) — written, then deleted.** The 5 was an unmeasured
number of mine. The gap it bounds is however long a caller takes between sampling and this
check, which nothing bounds at 5 s on a loaded runner. It would have made the flake *rarer*,
which is **worse**: a once-a-month CI red gets re-run and forgotten, and the production
misreport goes silent. Tolerating a symptom, not removing the cause.

**A clamp (`max(0, age)`) — rejected.** It reports age 0 for ANY future-dated mtime, so a
file dated hours ahead (clock skew on a shared FS, a restored backup, tampering) would read
as permanently fresh and claim "actively waiting" until the clock caught up. That is the
same indefinite-fire shape as the staleness bug the 30-minute upper bound exists for —
**an analogy to that incident, not a second instance of it; no skew incident has been
observed here.** `abs(age) < WINDOW` is worse still: it accepts a file dated 29 minutes in
the future. The asymmetry is load-bearing.

## Acceptance criteria

- [x] The mtime is compared against the real clock; `0 <=` restored unchanged; no tolerance
      constant survives.
- [x] **Mutation-verified in both directions.** With `age = now - int(mtime)` restored:
      exactly `test_a_stale_caller_sample_does_not_hide_a_fresh_directive` fails (1 failed,
      14 passed). With the fix: 15 passed.
- [x] `test_a_stale_caller_sample_does_not_hide_a_fresh_directive` — hands the function a
      `now` 5 s behind reality (what a slow fire has by the time it reaches this check)
      rather than hoping to lose a one-second race.
- [x] `test_a_future_dated_directive_does_not_read_as_waiting` — ONE fixture, two mtimes:
      `now-60` asserts True as a positive control, then `now+10800` asserts False, so the
      False is attributable to the mtime and not to another branch. It exists to pin the
      ASYMMETRY: it is the test that reddens if someone later "fixes" a negative age with
      `max(0, ...)` or `abs(...)` — the exact wrong turn taken and caught during this work.
- [ ] The full suite passes (the run that exposed this must go green). — **RUNNING at commit
      time**; the module's 15 tests plus ruff/mypy/pyright are green. Left unticked
      deliberately rather than held for 12 minutes of wall clock. **If it reds, the next
      commit says so** — an unticked box here means pending, not forgotten.

## Notes and lessons learned

- **A flake that only appears under load is a real bug reporting itself quietly.** The
  temptation is to re-run and move on; the 12-minute suite was the only condition under
  which a production defect became observable at all.
- **No advisor verdict was obtainable** — built-in tool absent, `fable-advisor:advisor` not
  installed (agent-not-found) despite `model-headroom fable` reporting the window reset. The
  tolerance-vs-clock call is my own analysis, corrected by a review fork.
