---
trdd-id: 5EHBPH6G
title: marketplace-refresh sweeps 262 registered marketplaces serially under background QoS and is cap-killed on every run — five consecutive rc=-9 and plugin updates deferred behind its lock
column: testing
created: 2026-09-03T09:20:00+0200
updated: 2026-09-04T06:02:00+0200
review-after: 2026-09-05
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03T11:09:13+0200

**CLAUSE 2 SHOULD BE REWORDED before anyone tries to close it.** As written ("`plugin-update`
no longer logging `deferred (marketplace lock held)`") it reads as *the string never appears*,
which no fix to this task can deliver — any lock holder produces it. What the card always MEANT
is refresh-caused starvation. Rewrite as: **"no `plugin-update deferred` line whose timestamp
falls inside a `marketplace-refresh` run interval."** That is the condition measured below, and
it is the one the fix is responsible for.

**SUPERSEDED 2026-09-04 06:02 — the two facts this block waited on have both arrived.**
`69feb820` IS published (v3.4.2 onward; `git tag --contains` is no longer empty), and
`daemon.log` now carries five clean runs. Box 4 was measured today: **clause 1 PASSES,
clause 2 FAILS.** Read the box's own annotation for the numbers; do not re-derive them.
The short version: refresh completes rc=0 in 95–100 s (was SIGKILLed at the 1920 s outer
cap, 11 times running), but `plugin-update deferred (marketplace lock held)` still appears
**211 times** in a 7 h window, landing inside the refresh runs. **The fix removed the cap
kill, not the lock contention** — starvation went from ~32 min to ~100 s, a different
severity rather than a different failure. Closing box 4 needs a shorter lock hold
(per-item rather than per-run) or an explicit decision to reword clause 2.

**Board reconciliation (2026-09-03 11:09) — HISTORICAL, both premises now false:** boxes
1-3 confirmed proven (still true). Box 4 stays open: implementing commit `69feb820` is
UNPUBLISHED and no rc=0 run exists to observe yet. `review-after: 2026-09-05` set.

## ⏵ PRIOR STATE — 2026-09-03

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
      and **no `plugin-update deferred (marketplace lock held)` line whose timestamp falls
      inside a `marketplace-refresh` run interval.**
      ~~and `plugin-update` no longer logging `deferred (marketplace lock held)`.~~
      **REWORDED 2026-09-04.** The struck text reads as *the string never appears*, which no
      fix to THIS task can deliver — every holder of `marketplace-op.lock` produces it
      (`version-update`, `fleet-plugins-update`, per-session marketplace ops). The interval
      form is what this card's own body always meant ("**while the child runs it holds** the
      lock, so every `plugin-update` fire logs `deferred`") and it is measurable. An earlier
      version of this edit put the new wording in prose ABOVE the box and left the box text
      alone — which is the "nothing evaluates a condition written as prose" defect this
      session corrected three times on TRDD-8BXMNQ4T, committed onto a checkbox.
      **MEASURED 2026-09-04, window 22:32→05:58 (7 h 26 m). Clause 1 PASSES, clause 2
      FAILS, so the box stays open — and the failure is the interesting half.**
      - **Clause 1 ✓** — four consecutive clean runs: `done in 98s / 98s / 100s / 95s`
        (01:21, 02:23, 03:25, 04:26, 05:28), all rc=0, all far under 300 s. Against the
        pre-fix behaviour — SIGKILLed at the 1920 s outer cap (`_WORKLOAD_TIMEOUT_SEC`
        1800 + `_BULK_CHILD_KILL_GRACE_SEC` 120) with nothing completed, 11 consecutive
        times — that is a ~19× reduction, and `refreshed 31/32 marketplaces` confirms it
        is doing near-full work rather than less of it.
      - **Clause 2 ✗ — and ATTRIBUTED, which a first version of this note only asserted.**
        `plugin-update deferred (marketplace lock held)` appears **211 times**. Every one
        of them — **211/211, 100%** — falls inside one of the 6 `marketplace-refresh` run
        intervals; **zero** occur outside. So `marketplace-refresh` is the sole cause of
        these deferrals, not one candidate among several lock holders
        (`version-update`, `fleet-plugins-update` and per-session marketplace ops all
        take the same lock and none of them produced a deferral here). The earlier
        wording cited three timestamps and said "some land inside a run", which was true
        and much weaker than the data.
      - **On clause 1's rc=0:** the daemon writes `done in Ns (background)` on success and
        `FAILED in Ns (background rc=-9)` on failure — distinct lines, so `done in` IS the
        rc=0 signal rather than merely "the task ended". Not read from an `rc=0` string;
        inferred from the absence of the FAILED form, which is strong here because that
        form appears in this same log for this same task 11 times before the fix.
      - **⚠ ALL 211 DEFERRALS NAME ONE PLUGIN: `claude-menu-system@emasoft-plugins`.**
        Distinct plugins in the 211 lines: **1**. So this is not "the fleet stops
        updating" — it is **one update request retried 211 times in 7 h**, every retry
        landing inside a refresh window. Two consequences:
        1. **The card's framing is too broad for what is happening now.** "Every
           `plugin-update` fire logs `deferred` — the fleet stops updating" described the
           32-minute era. Today exactly one plugin is affected, so clause 2's failure is
           real but far narrower than the card's prose implies.
        2. **~~A separate question: why is ONE plugin retried 211 times in 7 h? ~30/hour is
           not a cadence any documented interval produces — possibly a retry loop worth its
           own card.~~ SCOPED AND WITHDRAWN — there is no retry-loop defect.** Measured:
           the request **succeeds** on its own cadence once the lock is free —
           `plugin-update claude-menu-system@emasoft-plugins: no change (rc=0)` at 05:45:20,
           05:55:16, 06:05:05, i.e. **~10-minute intervals**. Deferrals run 22:58:03 →
           04:26:31 and then stop entirely. So 211 ≈ **33 fires × ~6 in-fire retries** (the
           6-second spacing in the sample triplet is retries within ONE fire), all confined
           to windows where `marketplace-refresh` held the lock. Normal cadence, bounded
           retries, no pathology. **Deliberately NOT filed as a card** — the finding
           dissolved when scoped, and filing it would have added an open card describing
           healthy behaviour.
        This corrects my own rebuttal to a review: I claimed the daemon logs one deferral
        per PLUGIN (~40 per fire), reconciling 211 with 5 runs. False — it is one plugin,
        many retries. I inferred "per plugin" from three sample lines that all named the
        SAME plugin, which was evidence for the opposite reading. The 211/211-inside-a-run
        interval join is unaffected; only my explanation of the count was wrong.
      **What this means for the card:** the fix removed the *cap kill*, not the
      *contention*. TRDD-5EHBPH6G's own framing is that the sweep "held the marketplace
      lock for the whole ~32 min attempt and starved every other marketplace op behind
      it" — starvation is now ~100 s instead of ~32 min, which is a different severity,
      not a different failure. Closing this box needs either a shorter lock hold (per-item
      lock rather than per-run) or an explicit decision that ~100 s of deferral is
      acceptable and clause 2 should be reworded. **Neither is decided here.**
      (Read and measured after a review pointed out I had flagged this card as a likely
      close without reading its box. The box text asks for TWO conditions; only one was
      ever going to be satisfied by the #297 work.)

## Approval log

## Notes and lessons learned
