---
trdd-id: ARTTXA7P
title: The daemon tick must derive its chore decision and its transition-log line from ONE liveness-file read, not up to three
column: testing
created: 2026-09-06T02:15:55+0200
updated: 2026-09-06T02:52:00+0200
implementation-commits: [a02c58de]
current-owner: janitor-main-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
parent-trdd: HXZ8B0IS
min-approval-requirement: none
npt: []
eht: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-06

Implemented and green. `scripts/lib/harness_backend.py` gained two pure helpers,
`runs_chores_from(probe)` and `claimed_chores_from(probe)`, and `server_runs_chores()` /
`claimed_chores()` now delegate to them over a single `server_liveness_probe()` call each
(their own external contracts — including the env-override short-circuit that skips the
file read entirely — are unchanged). `scripts/daemon.py`'s tick now takes ONE probe
(`harness_backend.server_liveness_probe()`) and derives `server_chores`, `claimed`, and the
transition-log line all from that one object; `_task_yielded_to_server` /
`_yielded_task_names` take an injected `claimed: AbstractSet[str]` instead of calling
`harness_backend.claimed_chores()` internally. Updated the 3 existing test call sites
(`tests/test_chore_coordination.py`, `tests/test_cold_cache_clear_server_lane.py`) to the
new arity and added 6 new tests pinning the `*_from(probe)` equivalence + override
precedence + the "one probe survives a fresh→stale flip with an unchanged answer" proof.
pytest/ruff/mypy/pyright all clean on every touched file.

Review finding (fork, 2026-09-06 02:36) folded in: the loop-EXIT gate
(`server_owns_every_chore()`, ~line 3624) sat ABOVE the tick's probe and took two reads of
its own, so "one read per tick" was false. Fix: `harness_backend.owns_every_chore_from(probe)`
(pure) + `server_owns_every_chore()` delegates to it over one probe; the tick now takes its
single probe BEFORE the exit gate and both the gate and the B2 block derive from it.
`tests/test_one_daemon_per_host.py`'s same-decision invariant now asserts the exit gate
uses the helper on `probe`, the spawn gate uses the wrapper, and the wrapper is a pure
delegation (source-text). NEXT ACTION: none — ready for the full-suite publish gate.

## Symptom

Commit e9dea96a (TRDD-HXZ8B0IS) made the daemon's chore-coordination yield/resume
transition line carry a `LivenessProbe` (ts, age, reason) so a flap could explain itself.
But the tick at `scripts/daemon.py` (~line 3630, pre-fix) decided
`server_chores = harness_backend.server_runs_chores()` with ONE read of
`~/.aimaestro/server-liveness.json`, and the transition log (~line 3638) did a SECOND read
via `harness_backend.server_liveness_probe()`. `_task_yielded_to_server` (~line 3024) called
`harness_backend.claimed_chores()`, which could read the file a THIRD time per due task. On
the stale/alive edge (a 30 s writer renaming between the reads) the logged reason could
describe a different read than the one that flipped the decision — defeating the point of
TRDD-HXZ8B0IS: attribution at exactly the edge it was built to explain.

## Fix

- Read the liveness file ONCE per daemon tick (`server_liveness_probe()` stays the single
  reader).
- Add pure helpers in `harness_backend.py`, `runs_chores_from(probe)` and
  `claimed_chores_from(probe)`, that derive from an already-taken probe what
  `server_runs_chores()` and `claimed_chores()` derive from a fresh read. The two public
  functions now delegate to these helpers; every other caller keeps its existing signature
  and behaviour (env-override precedence, fail-toward-coverage on no claim, etc.).
- In the daemon tick: take the probe once, derive `server_chores` and the claimed set from
  it, and pass the SAME probe to `_chore_coordination_message`.
- `_yielded_task_names` / `_task_yielded_to_server` accept the claimed set (previously
  computed via `harness_backend.claimed_chores()` inside `_task_yielded_to_server`) as a
  parameter instead of re-reading; both stay pure.

## Acceptance criteria

- [x] `harness_backend.runs_chores_from(probe)` / `claimed_chores_from(probe)` exist, are
      pure (no I/O), and `server_runs_chores()` / `claimed_chores()` delegate to them while
      keeping their own external contract (including the override short-circuit that skips
      the file read).
- [x] `daemon.py`'s tick reads the liveness file once per iteration and derives the yield
      decision AND the transition-log line from that one probe object.
- [x] `_task_yielded_to_server` / `_yielded_task_names` take an injected claimed set; no
      other call site's signature changed.
- [x] A real-file test proves the tick's decision and its logged reason come from the same
      read: take one probe while the file is fresh, let the file go stale, and show that
      deriving from the ORIGINAL probe object still answers as it did when taken (the
      mismatch TRDD-HXZ8B0IS wanted attributed is now impossible by construction).
- [x] A real-file test proves `server_runs_chores()` / `claimed_chores()` are unchanged for
      a fresh file, a stale file, and an absent file (delegation is transparent).
- [ ] Full suite green — at the publish gate.

## Notes

Filed as a depth-1 EHT of TRDD-HXZ8B0IS per the parent's own construction: the parent fixed
what the transition log SAYS; this fixes what it is SAYING IT ABOUT.

## Approval log
