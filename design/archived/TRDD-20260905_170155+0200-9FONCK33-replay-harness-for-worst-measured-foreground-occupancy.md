---
trdd-id: 9FONCK33
title: replay harness for worst measured foreground occupancy
column: complete
created: 2026-09-05T17:01:55+0200
updated: 2026-09-16T12:34:44+0200
current-owner: main-session
task-type: feature
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
external-refs: [TRDD-QJ5LP4W2, TRDD-8BXMNQ4T]
implementation-commits: [f2f7656d]
---

# Replay harness for worst measured foreground occupancy

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-05

- **HARNESS LANDED 2026-09-05T17:25 — column `todo` → `testing`.** New module
  `tests/test_daemon_foreground_replay.py`: `read_worst_pass_pattern(log_text)` groups
  foreground `task '<n>' starting`/`done in Ns`/`FAILED in Ns` line pairs into passes
  (new pass when the gap since the previous foreground `done`/`FAILED` line is >=10s —
  an inference from observed real-log timing, documented as such, not a log contract),
  drops any line containing `"(background"` (bulk-lane bodies never count toward the
  foreground budget), picks the pass with the largest summed occupancy, dedupes by
  first occurrence per name, and raises `ValueError` on a log with no parseable
  foreground bodies (2 tests). `_build_replay_tasks`/`_replay_and_assert` wire real
  `daemon.Task` objects (real `time.sleep`, no mocks) for every body in the winning
  pass — a floor name already in the pattern keeps its MEASURED body (never dropped);
  `oauth-rotator-tick` is appended with a nominal 1s body only if genuinely absent —
  stamp last-run deterministically oldest-first in pattern order (so the fix's
  oldest-last-run-first tie-break reproduces the measured dispatch order), monkeypatch
  `_FOREGROUND_BUDGET_SEC` to the real default scaled by `JANITOR_REPLAY_SCALE`
  (default 0.01), run `_run_due_tasks`, and assert (a) from daemon.log start-line
  offsets that `oauth-rotator-tick` dispatches before every non-floor body that ran,
  and (b) elapsed wall time <= `sum(scaled floor bodies) + scaled budget +
  max(scaled non-floor body)` (+ slack for scheduling overhead) — all three terms
  printed in the assertion message.
- **REAL-HOST-LOG PATTERN FOUND** (`~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/daemon.log`,
  9333 lines, pre-fix daemon — the fix landed later the same day): worst pass window
  `2026-09-05T14:53:52+0200`..`2026-09-05T14:58:27+0200`, bodies
  `session-liveness=166s, cold-cache-clear=85s, gh-notify-inbox=21s, oauth-recovery=0s`
  (total 272s) — no `oauth-rotator-tick` line in that pass, so the harness appended
  the nominal 1s stand-in. Replayed at scale=0.01 through the CANDIDATE-3 code: PASS —
  no defect found; the tick dispatches first (floor-first sort) and the bound held.
  Verified twice: once with `JANITOR_REPLAY_LOG` pointed at the real path directly
  (pytest's own test-isolation machinery redirects `Path.home()` under the plain
  `-p no:cacheprovider` run, so the default-path branch legitimately SKIPPED there —
  named in its skip message, not a defect).
- **Gates:** ruff (0), mypy on `scripts/` (0 — module lives in `tests/`, outside the
  gate's scope per this repo's existing convention), pyright full-project (0 errors/0
  warnings), pytest `tests/test_daemon_foreground_replay.py
  tests/test_daemon_foreground_budget.py` — 9 passed, 1 skipped (the real-log test
  under the default `Path.home()` branch, named above); with `JANITOR_REPLAY_LOG` set
  explicitly, all 10 pass.
- **daemon.py untouched** — this card only adds a test module.
- **TIGHTENED 2026-09-05T17:29 (coordinator review).** The original bound check could
  not catch a broken deferral: at scale 0.01 on the real-log pattern, bound≈1.97s +
  the old `epsilon=max(1.0, len(tasks)*0.1)`≈1.0s tolerated `cold-cache-clear`
  (0.85s) wrongly running after the crossing body. Fixed two ways: (1)
  `_predict_dispatch` now simulates the real dispatch loop from the SAME stamped
  order `_build_replay_tasks` assigned (floor bodies first in pattern order, then
  non-floor in pattern order — exactly what `_run_due_tasks`' floor-first/oldest-
  last-run-first sort reduces to under those stamps) to compute the exact
  expected STARTED/DEFERRED split; `_replay_and_assert` now asserts every started
  name has a `starting` line, every deferred name has NONE, and exactly one
  `chore-coordination: foreground budget` line exists iff anything was deferred —
  all three printed in the failure message. (2) `epsilon = 0.25 + 0.10 * bound`
  (proportional to the bound, not a flat/task-count-scaled slack that could swallow
  a real deferral bug). Re-verified: ruff/mypy/pyright clean; pytest 9 passed + 1
  named skip (default `Path.home()` branch, redirected by this repo's own
  test-isolation machinery); with `JANITOR_REPLAY_LOG` pointed at the real host log
  explicitly, all 10 pass, including the tightened deferral-set check.

## Why

TRDD-QJ5LP4W2's candidate-3 patch (landed 5f7f3dba) added a per-beat foreground budget
and survival floor to `scripts/daemon.py`, and pinned the mechanism with synthetic tests
using short, controlled durations. Acceptance box 3 requires more: "A test pins the
bound, and `oauth-rotator-tick` is shown still firing on cadence with the worst measured
occupancy pattern replayed." That box was ruled explicitly out of scope for the patch
(§F risk 3) and stays unticked — this card is the follow-up that closes it.

The box carries a load-bearing annotation from the parent card: **"THE OCCUPANCY PATTERN
IS A PARAMETER, NOT A CONSTANT."** 8BXMNQ4T's snapshot maxed at ~78 s; a wider 32 h
window found 102/137/191 s bodies. A harness hard-coded to either value pins a bound
that is either too low (passes a daemon that still skips cycles — the worst kind of
green) or stale the moment a wider window finds something larger, since a maximum is an
order statistic and the least stable thing a sample yields.

## What

A test harness that, at RUN TIME, reads the worst measured foreground-occupancy pattern
from the WIDEST `daemon.log` window available (never a hard-coded constant such as 78 s
or 191 s), replays that pattern through `_run_due_tasks` using real `Task` objects (no
mocks, per this repo's testing convention), and asserts `oauth-rotator-tick` still fires
within its 60 s cadence under the real budget/survival-floor code from candidate 3.

## Acceptance criteria

- [x] Harness reads the occupancy pattern as a parameter from the log window available
      when it runs (not a hard-coded duration) —
      `test_pattern_reader_picks_the_pass_with_the_larger_summed_occupancy` +
      `test_replay_real_host_log_worst_pattern_keeps_tick_within_cadence`
      (`tests/test_daemon_foreground_replay.py::read_worst_pass_pattern`).
- [x] Replay drives `_run_due_tasks` with real `Task` objects wired to the measured
      per-task durations, not mocks —
      `test_replay_synthetic_worst_pattern_keeps_tick_within_cadence` +
      `test_replay_real_host_log_worst_pattern_keeps_tick_within_cadence`
      (`_build_replay_tasks` constructs real `daemon.Task` objects with real
      `time.sleep` bodies).
- [x] Assertion: `oauth-rotator-tick` fires within its 60 s cadence throughout the
      replayed pattern — `_replay_and_assert`'s dispatch-order + bound assertions,
      exercised by both replay tests above.
- [x] Documented (module docstring or README) how to point the harness at a different
      log window (path + time range) — module docstring of
      `tests/test_daemon_foreground_replay.py` (`JANITOR_REPLAY_LOG` /
      `JANITOR_REPLAY_SCALE`).

## Notes and lessons learned

## Approval log

- 2026-09-16T12:34:44+0200 — COMPLETE by session. every acceptance box ticked, no open item, code long landed; closed on the 2026-09-16 triage (box counts verified first-hand).
