---
trdd-id: 9EAQS97B
title: A run_subprocess timeout is invisible to the caller's caller — the fail-open None must also leave one line on stderr
column: dev
created: 2026-09-05T21:08:27+0200
updated: 2026-09-05T21:08:27+0200
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

## Symptom

Five ids that fail identically in every full-suite run — `test_branch_protection.py` ×2,
`test_branch_protection_guard`, `test_gh_reply_watch` ×2 — all show the detector
subprocess with `returncode=0`, `stdout=''`, `stderr=''`. They pass alone. A solo run of
`tests/test_gh_reply_watch.py` on a loaded host (loadavg 20–60) failed 5 of 14 the same
way, including `test_first_fire_is_silent_and_baselines_the_cursor`, whose first fire has
no stamp to collide with — which refuted the shared-floor-stamp hypothesis
(`reports/board-drain/20260905_210746+0200-Q8PNPRTW-gh-reply-watch-floor-stamp-discriminator.md`).

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

- [ ] `run_subprocess(["sleep", "5"], timeout=0.2)` returns `None` AND the captured
      stderr contains `[run_subprocess] subprocess timed out` (new test, real `sleep`,
      no mock; scale the timeout through the existing seam if the harness multiplies it).
- [ ] The `FileNotFoundError` and `OSError` branches emit their reason the same way (one
      test for the binary-not-in-PATH case).
- [ ] Existing `run_subprocess` / `_log_fail_open` tests still pass; any test that asserted
      an EMPTY stderr on a fail-open path is updated to assert the new line instead.
- [ ] `uv run pytest tests/test_gh_reply_watch.py -q` once, on a host below loadavg 20:
      every failure that still occurs must now show the `[run_subprocess]` line in its
      captured stderr (paste the lines). Green is not required by this card; visibility is.
- [ ] ruff / mypy / pyright clean on the touched files.
- [ ] Full suite green — at the publish gate.

## Notes

Filed from the Q8PNPRTW discriminator worker's read of `state.py:1115-1185` and
`gh-reply-watch.py:99-159`, verified by the coordinator. EHT of 7NSRD8OV: until this
lands, that card's soak evidence undercounts timeouts.

## Approval log
