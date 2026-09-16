---
trdd-id: 9EAQS97B
title: A fail-open run_subprocess None must also leave one line on stderr
column: todo
created: 2026-09-05T21:08:27+0200
updated: 2026-09-16T12:33:55+0200
current-owner: janitor-main-session
assignee: lean-worker
task-type: bugfix
priority: high
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
parent-trdd: 7NSRD8OV
npt: []
eht: []
---

See also: TRDD-Q8PNPRTW (where the empty-stdout cluster was chased), TRDD-7NSRD8OV (owner
of the timeout-under-load class).

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-05

`_log_fail_open` in `scripts/lib/state.py` now prints `[run_subprocess] <detector-or-"-">
<reason>: <cmd[0]>` to `sys.stderr` (added `import sys` at module top), alongside its
existing unconditional `<detector>.log` write; never raises. Two new tests in
`tests/test_run_subprocess_fail_open_logging.py`: a real-timeout case (`@no_timeout_scale`,
real `sleep`-equivalent child, `capfd`) and a missing-binary case. All 7 tests in that file
pass; ruff/mypy/pyright clean on both touched files. `test_gh_reply_watch.py` was NOT run
(loadavg 31.21 > the 20 gate) — visibility-only acceptance box left unchecked, not a
failure. Full suite not run (out of this worker's file scope). NEXT ACTION: someone below
loadavg 20 runs `uv run pytest tests/test_gh_reply_watch.py -q` and pastes any
`[run_subprocess]` lines from failing captures, then closes the remaining two boxes.

## Symptom

Five ids that fail identically in every full-suite run — `test_branch_protection.py` ×2,
`test_branch_protection_guard`, `test_gh_reply_watch` ×2 — all show the detector
subprocess with `returncode=0`, `stdout=''`, `stderr=''`. They pass alone. A solo run of
`tests/test_gh_reply_watch.py` on a loaded host (loadavg 20–60) failed 5 of 14 the same
way, including `test_first_fire_is_silent_and_baselines_the_cursor`, whose first fire has
no stamp to collide with — which refuted the shared-floor-stamp hypothesis
(`reports/board-drain/20260905_210746+0200-Q8PNPRTW-gh-reply-watch-floor-stamp-discriminator.md`).

The fix's stderr line is emitted from `_log_fail_open`, which is the single call site for
all three of `run_subprocess`'s fail-open branches — `TimeoutExpired`, `FileNotFoundError`
(binary not in PATH), and `OSError` — so it covers every fail-open mechanism, not only
timeouts. "Timeout" in the original title named the measured trigger for this investigation,
not the only mechanism the fix addresses; the title has been corrected accordingly.

## Mechanism (read from source)

`scripts/lib/state.py::run_subprocess` catches `subprocess.TimeoutExpired`, calls
`_log_fail_open(detector_name, "subprocess timed out after …", cmd)` — which writes ONLY
to `<detector>.log` — and returns `None`. Every caller in `gh-reply-watch.py`
(`if proc is None or proc.returncode != 0: return 0`) and, by the same idiom, in the
other 18 detectors that call `run_subprocess`, turns that `None` into a silent exit 0.
So a timed-out `gh`/`uv run` hop under load is indistinguishable, from outside the
process, from "nothing to report". The unit-8 category-D count (1 and 2 raised
`TimeoutExpired`) is therefore a floor: the swallowed ones never reach a traceback, and
the RULING's "zero category-D" bar cannot be checked against them.

Fail-open is the right production posture (a missed poll costs a delayed notification,
not a broken heartbeat) — the defect is that the reason leaves no trace on the channel
the caller's caller can see.

## Fix requirement

`_log_fail_open` keeps its unconditional log-file line AND writes the same one line to
`sys.stderr` (prefix `[run_subprocess] `, reason, the command's first token). Nothing
else changes: still returns `None`, still never raises. Under the heartbeat that line
lands on the detector's inherited stderr, which is not the stdout token channel the
dispatcher parses, so the `[janitor-…]` contract is untouched. Do not gate it on a
test-harness env var — production code must not carry a test-only branch, and a
timed-out detector is exactly the kind of thing a human reading the fire should see.

## Acceptance criteria

- [x] `run_subprocess([sys.executable, "-c", "...sleep(5)"], timeout=0.1)` returns `None`
      AND the captured stderr contains `[run_subprocess] <detector> ... timed out` (real
      child, no mock; `@pytest.mark.no_timeout_scale` drives the timeout to completion
      without the suite-wide scale seam stretching it past the child's lifetime — same
      pattern the existing timeout tests in this file already use). Format carries the
      detector name per coordinator decision: `[run_subprocess] <detector-or-"-"> <reason>: <cmd[0]>`.
- [x] The `FileNotFoundError` branch emits its reason the same way (binary-not-in-PATH test added).
- [x] Existing `run_subprocess` / `_log_fail_open` tests still pass (7/7); none asserted an
      empty stderr, so none needed updating.
- [ ] `uv run pytest tests/test_gh_reply_watch.py -q` once, on a host below loadavg 20 —
      SKIPPED this run: `sysctl -n vm.loadavg` read 31.21 at verification time.
- [x] ruff / mypy / pyright clean on the touched files (`scripts/lib/state.py`,
      `tests/test_run_subprocess_fail_open_logging.py`).
- [ ] Full suite green — at the publish gate (not run here; scope was the two named files).

## Notes

Filed from the Q8PNPRTW discriminator worker's read of `state.py:1115-1185` and
`gh-reply-watch.py:99-159`, verified by the coordinator. EHT of 7NSRD8OV: until this
lands, that card's soak evidence undercounts timeouts.

On the channel: `dispatch.py::_run_detector` captures only `stdout` (`subprocess.run(...,
stdout=subprocess.PIPE, ...)`) — `stderr` is never passed, so it is inherited straight
through to the dispatcher stub's own stderr. dispatch.py never reads `.stderr` anywhere
(confirmed by grep — zero hits, including in the `TimeoutExpired` handler, which reads
only `exc.stdout`). So a `[run_subprocess]` line lands in the heartbeat fire's tool
result (the stub's stderr stream) but never in what the agent prints to the human — it
does not enter the `[janitor-…]` stdout-token contract the owner ratified 2026-08-12,
and it is not a drift/finding line. That is deliberate, not a gap this card leaves open:
a detector silently skipping its own subprocess is exactly the kind of thing a human
reading the raw fire output should be able to see, without it competing for space in the
quiet-filtered summary the dispatcher hands the agent.

## Approval log
- 2026-09-16T12:33:55+0200 — column → todo. no session working it for 7-13 days while column claimed testing; re-columned honest (triage 2026-09-16)
