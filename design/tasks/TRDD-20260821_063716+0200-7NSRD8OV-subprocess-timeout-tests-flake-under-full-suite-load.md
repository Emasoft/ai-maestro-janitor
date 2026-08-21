---
trdd-id: 7NSRD8OV
title: Tests that shell out with a 5s timeout flake under full-suite load and can block a publish
column: todo
created: 2026-08-21T06:37:16+0200
updated: 2026-08-21T07:21:05+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
approval-tier: 0
scope: project
npt: []
eht: []
---

# Subprocess-timeout tests flake under full-suite load

## Why

`uv run pytest` is the publish gate (`publish.py::_gate_tests`). A test that fails only under
the load the full suite itself creates will therefore block a publish at random, and — worse —
send whoever is publishing to debug a component that is not broken. Measured twice in one
session, on two unrelated tests:

1. `tests/test_pkg_manager_guard.py` timed out during a publish run at load avg 83; passed
   27/27 isolated immediately after.
2. `tests/test_window_burn_rate.py::test_agentlens_cause_prefers_cli` failed inside a 13-minute
   full-suite run; on the next full run the failure MOVED to
   `test_agentlens_cause_kept_when_material` in the same family; then 6 consecutive isolated
   runs of that file passed 54/54.

3. Same session, a later full run: `test_branch_protection.py::test_fires_when_unprotected`,
   `test_branch_protection_guard.py::test_apply_acts_when_only_one_baseline_present`, and
   `test_gh_reply_watch.py::test_first_fire_is_silent_and_baselines_the_cursor` failed together
   inside a 12m33s full run — **all three passed isolated in 8.37s**. That takes the class from
   "two odd tests" to **5 tests across 4 files**, which is the argument for fixing the CLASS
   rather than the instances: whichever subprocess lands in a slow window is the one that fails,
   so chasing individual tests will never converge.

The moving failure is the tell. Both tests call `agentlens_probe.probe_json`, which runs a
`tmp_path` shell script through `subprocess.run(..., timeout=_TIMEOUT_S)` with
`_TIMEOUT_S = 5.0` (`scripts/lib/agentlens_probe.py:54`). `probe_json` is fail-OPEN by design:
a timeout returns `None`, the clause becomes `""`, and the assertion fails with an empty string
rather than an error naming a timeout. Isolated run times for that one file were measured
swinging **3.7s → 13.3s** — against a 5.0s per-probe ceiling. Whichever probe happens to land
in a slow window is the test that fails, which is why it is never the same one.

**The failure LOOKS like a logic bug and is a scheduling one.** That is the expensive part: an
empty-string assertion failure gives no hint that a timeout occurred, so the natural response is
to go read the clause-building code, which is correct.

## What

Not "raise the timeout until it stops" — that just moves the threshold and re-hides the problem
on a slower machine or a busier day. Options to decide between, cheapest first:

1. **Do not shell out at all in these tests.** The probe's CONTRACT (parse JSON stdout, fail
   open) is what is under test; the fact that the JSON arrives via `/bin/sh` is incidental.
   Injecting the payload directly removes the timing dependency outright and makes the tests
   faster. This is the likely right answer for most of them — but check first whether any test
   is deliberately exercising the real `subprocess` path (argv splitting, non-zero exit,
   genuine timeout); those must keep a subprocess and get option 2 or 3.
2. **Make the test's timeout explicit and generous** where a real subprocess is required —
   `probe_json` already takes `timeout=` as a keyword, so a test can pass its own without
   changing the 5.0s production default.
3. **Fail loudly on timeout in tests**: assert the probe returned non-None before asserting on
   the clause, so a load flake reports "probe timed out" instead of an empty string. Cheap, and
   worth doing regardless of 1/2 — it converts a misleading failure into an honest one.

Sweep for the whole class, not just these two: grep the suite for tests that build a script in
`tmp_path` and invoke it through a production helper with a fixed timeout.

## Acceptance

- [ ] the class is enumerated (which tests shell out through a fixed-timeout helper), not just
      the two that happened to fail
- [ ] each one either stops shelling out, or takes an explicit test-side timeout, or asserts the
      probe succeeded before asserting on its output
- [ ] production defaults (`_TIMEOUT_S = 5.0`) are UNCHANGED — this is a test-harness defect,
      and loosening a production timeout to make a test pass would trade a real guarantee for a
      green tick
- [ ] evidence: the full suite run back-to-back under load with no flake in this family

## Approval log
