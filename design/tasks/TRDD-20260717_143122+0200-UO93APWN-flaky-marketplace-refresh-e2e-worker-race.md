---
trdd-id: UO93APWN
title: Flaky e2e worker race in test_marketplace_refresh_scoped
column: todo
created: 2026-07-17T14:31:22+0200
updated: 2026-07-17T14:31:22+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
severity: low
---

## Problem

The end-to-end tests in `tests/test_marketplace_refresh_scoped.py` (detector spawns a
DETACHED worker → worker calls the spy `claude`) fail NON-DETERMINISTICALLY. Proven
2026-07-17 on an identical tree: `pytest tests/test_harness_exclusion.py
tests/test_marketplace_refresh_scoped.py` → pass, pass, fail across three consecutive
runs; WHICH e2e test fails varies (`test_per_session_refreshes_each_unique_marketplace`
or `test_disabled_plugins_are_skipped`). Failure shape is always the same: the worker's
claude-call log stays empty, i.e. the detached worker either never ran the refresh or
had not run it before `_wait_for_worker`'s poll gave up.

Each test DOES get an isolated tmp project + `JANITOR_GLOBAL_STATE_DIR`, so it is not
cross-test state via files. Suspects, in order: (1) `_wait_for_worker` poll budget too
tight under load; (2) the detached worker's spawn (`uv run` shim in `_make_uv_bin`)
occasionally slow/cold; (3) a lingering DETACHED worker process from the previous test
interacting with the spawn-skip ("prior worker still alive → skip cleanly") logic in a
way the per-test tmp dirs do not actually isolate (worker PID tracking location —
verify which dir it really lives in).

## Fix criteria

Reproduce the empty-log case with added tracing, identify which suspect it is, fix the
TEST (or the detector's PID-tracking isolation if #3 is real), then prove 20
consecutive paired runs green. Browser-test rule applies in spirit: every detached
process a test spawns must be awaited or killed before the test returns.

## Notes and lessons learned
