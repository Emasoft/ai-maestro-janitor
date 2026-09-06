---
trdd-id: HXZ8B0IS
title: A chore-coordination transition must log the liveness file's ts, age and the None reason so an ownership flap attributes itself
column: testing
created: 2026-09-05T21:13:51+0200
updated: 2026-09-06T02:15:55+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
npt: []
eht: [ARTTXA7P]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-06

**2026-09-06 — EHT filed:** a review of the daemon tick found this card's own fix still let
the tick read the liveness file up to 3x per iteration (`server_runs_chores()`,
`claimed_chores()` inside `_task_yielded_to_server`, and the transition-log probe), so the
logged reason could still describe a different read than the one that flipped the decision
on the stale/alive edge. Filed depth-1 EHT **TRDD-ARTTXA7P** (`design/tasks/`, `column: dev`)
to make the whole tick derive from ONE probe object. Does not change this card's own
acceptance boxes.

Implemented and green. `harness_backend.py` gained `LivenessProbe` (dataclass: reason /
ts / age / exc_type / capabilities) + `server_liveness_probe()`; `server_capabilities()`
now delegates to it and keeps its exact signature/return type. `daemon.py` gained the pure
`_chore_coordination_message(yielded, probe)` and calls it once per transition (unchanged
call site cadence — transition-only, no per-tick logging). Tests added in
`tests/test_harness_backend.py` (probe reasons: absent/malformed/read-error/stale/alive,
89s/91s boundary, delegation contract) and `tests/test_chore_coordination.py` (transition
message carries ts/age/reason both directions, 89/91s boundary, absent-has-no-ts).
pytest/ruff/mypy/pyright all clean on touched files. NEXT ACTION: none — ready for
ai_review/testing at the full-suite publish gate (last acceptance box).

See also: ai-maestro TRDD-OUAQARPL (server side of the same flap), TRDD-5ADHOZE4 (their
measurement card), TRDD-LU0C5KAR (why the reader gates on freshness alone).

**2026-09-05T22:08 — column → testing; pyright fix-forward before commit:** the worker's
"pyright clean" did not hold — `_chore_coordination_message(yielded: set[str], ...)` reddened
on the two test call sites that pass a `frozenset` (`claimed_chores()`'s type); the parameter
is now `AbstractSet[str]`. **Server-side pair, from `ai-maestro-d5`:** their writer
(`lib/server-liveness.ts`, 30 s `setInterval`, tmp+rename atomic write) measured 30-37 s
beats concurrent with our 18-sample sawtooth (peak age 35 s); zero failed-write lines and no
restart since the 11:16 boot, so period, restart and write failure are all ruled OUT for the
15:01-19:18 flap. Their commit aa961973 (branch governance-rules, TRDD-OUAQARPL) adds a
`[server-liveness] late beat: gap <ms>ms exceeds 2x interval <ms>ms` stderr warn, transition-
only, live on their next server restart. Reading the pair on the next flap: a `late beat`
line on their side = writer was late; none = reader misjudged or the file was fine.
Candidate they recorded, NOT a finding: the 19:19:17 transition is 2 s after a
`[JanitorPublish]` beat in their error log, the one absorbed chore doing synchronous fs work
on their main thread. Host loadavg was 27-31 at 19:11-19:18 (our soak sampler), but no load
data exists for 15:01-18:22, so load is a correlation at one endpoint only.

## Symptom

`daemon.log` on 2026-09-05 shows 25 chore-coordination transitions; between 15:01 and
19:18 the janitor's own `oauth-rotator-tick` runs are interleaved with "yielding to active
ai-maestro server" lines, then continuous yielding from 19:19:17. Reported by the
ai-maestro hub session; two rotators alternately deciding is the flap their card measures.
Nothing on our side records WHY a tick read the server as gone.

## Mechanism (read from source)

`scripts/daemon.py:3610-3621` resolves `harness_backend.server_runs_chores()` once per
loop tick and logs only when the yielded set flips ("log transitions, not every tick").
`scripts/lib/harness_backend.py:286-310 server_capabilities()` returns None for four
different reasons — file absent, `ts`/`capabilities` malformed, `now - ts > 90`
(`LIVENESS_STALE_AFTER_S`, line 254), or ANY exception in the bare `except Exception`
(a partial read during a non-atomic rewrite lands here) — and the caller collapses them
to one bool. Measured 21:13:50: the live file's `ts` age was 86.6 s (mtime age 85.9 s),
against a reader window of 90 s and a docstring that says the server rewrites every 30 s.
A file routinely ~86–90 s old sits on the edge, and a 60 s tick lands alternately inside
and outside the window — the interleave, with no restart needed. One sample.

## Fix requirement

- `server_capabilities()` (or a sibling returning a small result) exposes the reason:
  `absent | malformed | stale(age=<s>) | read-error(<exc type>)` plus the raw `ts` and
  the computed age when the file parsed.
- The transition log line at `daemon.py:3614-3621` appends that reason, `ts` and age on
  BOTH directions (yield and resume). Transition-only — no per-tick logging in the edge
  zone: a flap IS a series of transitions, and each transition line already carries
  reason + ts + age, so the series is already recorded without it. Per-tick logging at
  a 60s tick would emit ~1440 lines/day for as long as the file sits at 90-180s age —
  exactly the state the transition-only design in `daemon.py` was written to keep quiet.
- No behaviour change to the verdict itself: this card only makes the verdict explain
  itself. Fail-safe semantics (no server visible ⇒ run everything) stay.
- `server_capabilities()` (or a sibling returning a small result) exposing the reason is
  mandatory as specified above — changing its return type ripples through
  `server_is_alive`/`server_runs_chores`/every caller, so do this once, correctly.

## Acceptance criteria

- [x] A test feeds a liveness file aged 89 s and 91 s and asserts the reason string and
      the age appear in the transition log line for each.
- [x] A test with a malformed file asserts `malformed`; a partial-JSON file asserts
      `read-error`.
- [x] `uv run pytest` on the daemon/harness_backend test files green; ruff/mypy/pyright
      clean on the touched files.
- [ ] Full suite green — at the publish gate.

## Notes

Filed from the ai-maestro hub session's measured report (their
`reports/lean-worker/20260905_210705+0200-5ADHOZE4-investigation.md`) and this session's
own read + one probe of the live file. The cadence/atomicity of the server's writer is
the hub's to measure; asked in the reply.

## Approval log
