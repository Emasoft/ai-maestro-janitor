---
trdd-id: 5EHBPH6G
title: marketplace-refresh sweeps 262 registered marketplaces serially under background QoS and is cap-killed on every run — five consecutive rc=-9 and plugin updates deferred behind its lock
column: testing
created: 2026-09-03T09:20:00+0200
updated: 2026-09-03T09:46:54+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
severity: high
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [daemon, marketplace, plugin-update, workload-cap]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
created-by: heartbeat drift line 2026-09-03 03:06 + diagnosis report
---

# marketplace-refresh is cap-killed on every run

## Measured (daemon.log, 2026-09-03)

| run start | outcome |
|---|---|
| 00:54 | FAILED in 1938 s, rc=-9, consecutive=2 |
| 02:27 | child pid 73836 exceeded the workload cap — killed; FAILED 1937 s, consecutive=3, quarantined +3600 s |
| 04:59 | child pid 77569 killed 05:31; FAILED 1934 s, consecutive=4 |
| ~06:30 | consecutive=5 |

While the child runs it holds `global-state/marketplace-op.lock`, so every
`plugin-update` fire logs `deferred (marketplace lock held)` — the fleet stops updating for
the whole 32-minute window, every hour. The completion stamp
`marketplace-refresh.last-run.ts` is written on failure too, so nothing reported this until the
heartbeat's task-quarantine drift line.

## Cause (diagnosis: `reports/board-drain/20260903_091701+0200-marketplace-refresh-diagnosis.md`)

- The task runs `claude plugin marketplace update` for **all registered marketplaces
  serially**. This host has **262** entries in `~/.claude/plugins/known_marketplaces.json`
  (289 dirs under `~/.claude/plugins/marketplaces/`) — the corpus-distillation work registered
  hundreds of one-off community marketplaces that back no installed plugin.
- The child runs under `taskpolicy -b` + nice (`daemon.py:512`, `daemon_throttle.py`), so
  262 serial network fetches at background QoS exceed the 1800 s inner deadline
  (`daemon.py:323`, `437-456`) — which never actually fires — and are SIGKILLed only by the
  outer 1920 s watchdog (`daemon.py:2488-2498`). Hence the constant ~1935 s / rc=-9.

## Fix

1. **Refresh only marketplaces that back an installed plugin** (derive the set from
   `installed_plugins.json` / the cache dir), plus the ones named in
   `CLAUDE_PLUGIN_OPTION_MARKETPLACE_REFRESH_EXTRA`. On this host that is a handful, not 262.
2. Per-marketplace timeout (`CLAUDE_PLUGIN_OPTION_MARKETPLACE_REFRESH_PER_ITEM_S`, default
   60) so one hung remote cannot consume the whole budget; a timed-out entry is logged and
   skipped, never retried in the same run.
3. Make the inner 1800 s deadline actually fire (it is dead code today) and write
   `last-run.ts` **only on success**; on failure write `last-failure.ts` so the stale-stamp
   detector sees the truth.
4. Surface the count: the task logs `refreshed N/M marketplaces in T s`.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03

Implemented (`scripts/daemon.py`, `scripts/lib/marketplace_refresh_plan.py`, tests). Gates
clean (`ruff`, `mypy`, targeted `pytest` — 84 tests: 73 daemon/marketplace unit +
11 `test_daemon_integration.py`). Not yet published/observed live (box 4).

- **Fix 1 (plan)** — new `scripts/lib/marketplace_refresh_plan.refresh_plan()`: installed-
  backing marketplaces (from `installed_plugins.json`, `<plugin>@<mkt>` keys) ∪
  `CLAUDE_PLUGIN_OPTION_MARKETPLACE_REFRESH_EXTRA`. `task_marketplace_refresh` loops this
  plan calling `claude plugin marketplace update <name>` per item (same argv shape
  `_consume_plugin_update_requests` already used) — the bulk no-name call is GONE.
- **Fix 2 (per-item timeout)** — `CLAUDE_PLUGIN_OPTION_MARKETPLACE_REFRESH_PER_ITEM_S`
  (default 60s) via `_run_workload_once` per item; a timeout/failure is logged and skipped,
  never retried in the same run. The run only counts as FAILED (raises → normal
  quarantine/backoff bookkeeping) when EVERY item failed.
- **Fix 3, reworked per orchestrator review (2 real bugs found, not the diagnosed one)**:
  - The 1800s single-call deadline is now moot FOR THIS TASK (no more single bulk call to
    apply it to) — not "made to fire", just no longer reachable here. Left untouched for
    its other caller (`task_version_update`, line ~785).
  - **Real bug A (found via advisor + daemon.log)**: `_run_workload`'s retry gave attempt 2
    a FRESH `_WORKLOAD_TIMEOUT_SEC`, not what was left of the shared budget — daemon.log.1
    showed a retry ~21 min into a 30 min budget getting another full 1800s, so the outer
    ~32 min watchdog did 100% of the killing. Fixed: `_run_workload` now shares ONE deadline
    across attempts (`math.ceil` remaining, never a truncated-to-0 first grant). New test:
    `tests/test_daemon.py::test_run_workload_retry_does_not_get_a_fresh_full_timeout`.
    `task_marketplace_refresh` itself never hits this path anyway (uses
    `_run_workload_once` directly, max_attempts=1-equivalent by construction).
  - **Real bug B (found empirically — my own test failed against real `taskpolicy`)**:
    `_run_workload_once`'s kill path SIGKILLed only `proc.pid` (the `taskpolicy -b` launcher
    itself), not the real workload it forks — an orphaned, still-running, pipe-holding
    child. This is why the OLD inner deadline never visibly stopped anything: it was
    detecting the timeout correctly, just unable to kill through a launcher prefix. Fixed:
    `start_new_session=True` + `os.killpg` (mirrors what `poll_background`'s OUTER watchdog
    already did for the identical reason), with a `proc.kill()` fallback.
  - **DROPPED per orchestrator correction**: "write last-run.ts only on success" is NOT
    implemented — `Task.run`/`poll_background` write it unconditionally for every task
    (daemon_watchdog.py's FAILING-BUT-RUNNING logic + `time_until_due`'s backoff depend on
    that invariant machine-wide). That semantics change is a separate, wider-blast-radius
    TRDD-FFXGPZEI (backburner) — not this one.
- **Fix 4 (log line)** — `marketplace-refresh: refreshed N/M marketplaces in Ts`, implemented.
- Test isolation fix: `tests/test_daemon_integration.py`'s harness now pins
  `CLAUDE_CONFIG_DIR` to a tmp dir with one `installed_plugins.json` record — without it the
  two marketplace-refresh integration tests silently depended on the REAL host's install
  state (empty on a clean CI runner ⇒ empty plan ⇒ the CLI never gets invoked at all).

**NEXT ACTION**: publish, then after the next `marketplace-refresh` cadence fires, check
`daemon.log` for one run finishing rc=0 in <300s (32 marketplaces measured on this dev host,
well under budget) and confirm no more `plugin-update deferred (marketplace lock held)`
lines — tick acceptance box 4 from that observation.

**Fable advisor**: not consulted directly — this session (lean-worker) has no Agent tool.
The orchestrator relayed advisor review at two points mid-task (both addressed above); no
independent verdict was obtained by this session itself.

## Acceptance

- [x] Unit test: with 3 installed plugins from 2 marketplaces and 200 registered ones, the
      refresh plan contains exactly those 2 (+ extras from the option). —
      `tests/test_marketplace_refresh_plan.py::test_refresh_plan_is_installed_backing_plus_extras`
      (+ 4 more planner unit tests, all passing).
- [x] Unit test: a per-item timeout skips the entry and the run still succeeds. —
      `tests/test_daemon_marketplace_refresh_task.py::test_per_item_timeout_skips_and_run_still_succeeds`
      (real fake-`claude`-on-PATH subprocess, real timeout, `@pytest.mark.no_timeout_scale`).
- [x] ~~Unit test: the stamp is untouched after a failed run; `last-failure.ts` is written.~~
      **DROPPED — deferred to TRDD-FFXGPZEI** (see STATE above). Replaced with two tests
      that DO match what shipped: `test_all_items_failing_is_a_failed_run` and
      `test_a_partial_success_is_not_a_failed_run` (both in
      `tests/test_daemon_marketplace_refresh_task.py`).
- [ ] Live: `daemon.log` shows one `marketplace-refresh` run finishing with rc=0 in < 300 s
      and `plugin-update` no longer logging `deferred (marketplace lock held)`.

## Approval log

## Notes and lessons learned
