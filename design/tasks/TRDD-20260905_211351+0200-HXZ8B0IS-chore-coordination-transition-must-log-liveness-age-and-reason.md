---
trdd-id: HXZ8B0IS
title: A chore-coordination transition must log the liveness file's ts, age and the None reason so an ownership flap attributes itself
column: todo
created: 2026-09-05T21:13:51+0200
updated: 2026-09-05T21:13:51+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
npt: []
eht: []
---

See also: ai-maestro TRDD-OUAQARPL (server side of the same flap), TRDD-5ADHOZE4 (their
measurement card), TRDD-LU0C5KAR (why the reader gates on freshness alone).

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
  BOTH directions (yield and resume), and the daemon also logs it once per tick while
  the verdict stays "stale/absent" but the file is younger than 2× the window (the
  edge zone), so a flap leaves a series, not just its endpoints.
- No behaviour change to the verdict itself: this card only makes the verdict explain
  itself. Fail-safe semantics (no server visible ⇒ run everything) stay.

## Acceptance criteria

- [ ] A test feeds a liveness file aged 89 s and 91 s and asserts the reason string and
      the age appear in the transition log line for each.
- [ ] A test with a malformed file asserts `malformed`; a partial-JSON file asserts
      `read-error`.
- [ ] `uv run pytest` on the daemon/harness_backend test files green; ruff/mypy/pyright
      clean on the touched files.
- [ ] Full suite green — at the publish gate.

## Notes

Filed from the ai-maestro hub session's measured report (their
`reports/lean-worker/20260905_210705+0200-5ADHOZE4-investigation.md`) and this session's
own read + one probe of the live file. The cadence/atomicity of the server's writer is
the hub's to measure; asked in the reply.

## Approval log
