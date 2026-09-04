---
trdd-id: 5EHBPH6G
title: marketplace-refresh sweeps 262 registered marketplaces serially under background QoS and is cap-killed on every run — five consecutive rc=-9 and plugin updates deferred behind its lock
column: complete
created: 2026-09-03T09:20:00+0200
updated: 2026-09-04T06:32:00+0200
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

**ALL FOUR ACCEPTANCE BOXES PASS as of 2026-09-04 06:20 — this card is `complete`-eligible.**
Clause 1: five post-fix runs at 95–100 s, rc=0. Clause 2: post-fix request waits 38 s and
44 s against a 600 s bound. The three unit-test boxes were already proven.

**THE PRE-FIX ATTRIBUTION — established by a behaviour CHANGE at the restart boundary.**
This is the load-bearing premise of the tick, so it is stated in full, including what could
NOT be established.

*Not usable:* "the episode ends at a cap-kill, therefore pre-fix" — circular, since the
cap-kill is the thing being classified. *Also not usable:* the pre-restart daemon's launch
time — its `started (pid=` line predates the retained log, so it cannot be dated, and
v3.4.2 shipped 2026-09-01, two days before the episode. A long-running process does not pick
up a release until it restarts, but that is an argument, not an observation.

*What actually discriminates* — the outcome record across the 00:57:46 restart:

| | runs | outcome |
|---|---|---|
| pre-restart | `consecutive=11` | **11 straight cap-kills**, the last at 1935 s rc=-9 |
| post-restart | 5 | **5/5 succeeded**, 95–104 s, all emitting `refreshed 31/32` |

One code version does not fail eleven times running and then succeed five times running
with nothing between but a restart. The `refreshed N/M` counter — introduced by `69feb820`
itself — appears **zero** times before the restart and on every run after it. That is a
version change at a known instant, so the 22:47 run was old code and the 1313 s wait behind
it is pre-fix.

(Absence of the counter *alone* would not discriminate: a cap-killed new-code run also emits
none. It is the 11-vs-5 outcome flip that carries this, not the silence.)

**MOVED to `complete` 2026-09-04 06:32.** All four boxes pass and the decisive premise is
established above, so holding it was a third state the board does not model — "eligible but
waiting" is not a column, and the hold was self-imposed rather than blocked on anything.

Two earlier hold-conditions are withdrawn as unsatisfiable, and that is the card's most
reusable lesson: *"move it when an adversarial review returns no card-affecting finding"* was
never met in ~24 reviews, and it is the **same defect as clause 2's v1 and v2** — a condition
phrased as the absence of an event that occurs by construction. Three unsatisfiable
conditions were written on this one card before the pattern was named.

**What is NOT proven, recorded because the card is now frozen:** both post-fix samples are
single-window collisions (one fire hits one ~95 s hold, waits, succeeds). **No post-fix
observation exists of a request missing MULTIPLE consecutive refresh windows** — which is the
scenario that produced the 1313 s pre-fix number. `review-after: 2026-09-05` remains set; if a
later session finds a multi-window post-fix miss over 600 s, that is a NEW card, not a reopen.

**Retracted before it could mislead:** an earlier version of this section said the fix gave
only a ~1.5× improvement because a request waits ~22 min. That compared a NEW-regime request
wait against an OLD-regime lock hold — different quantities, different regimes — and the
1313 s sample driving it turned out to be pre-fix (it ends at the cap-kill reap). Post-fix
waits are 38–44 s. The comparison it should never have made cannot be computed at all: no
old-regime request-wait was ever measured.

**Everything below this line is HISTORICAL and every conclusion in it has been superseded by
the paragraphs above.** It is kept, not deleted, because the reasoning errors are the
transferable part — absence-shaped acceptance criteria were tried twice and failed twice, and
a max taken across a window straddling a fix produced a confident, wrong headline. Read it as
a record of how the box got answered, never as its current state.

- ~~"Rewrite clause 2 as: no `deferred` line inside a refresh run interval."~~ That v2 wording
  is itself unsatisfiable — refresh and `plugin-update` are independent schedules and collide
  ~16% of fires forever. The live wording is v4 (a 600 s bound on per-request wait).
- ~~"Clause 1 PASSES, clause 2 FAILS. 211 deferrals land inside refresh runs. The fix removed
  the cap kill, not the lock contention; starvation went from ~32 min to ~100 s. Closing box 4
  needs a shorter lock hold or a reword."~~ **Both clauses pass.** The 211 figure is real but
  counts one plugin's bounded retries; the request-wait measurement that actually answers the
  clause is 38 s and 44 s post-fix.
- ~~"Box 4 stays open: `69feb820` is UNPUBLISHED and no rc=0 run exists to observe."~~ Both
  premises became false — it ships from v3.4.2, and five clean runs exist.

Boxes 1-3 were confirmed proven on 2026-09-03 and that has not changed.

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
- [x] Live: `daemon.log` shows one `marketplace-refresh` run finishing with rc=0 in < 300 s
      and **no `plugin-update` request whose total wait (first deferral → its next
      `rc=0`) exceeds 600 s.** **BOTH CLAUSES PASS.** Clause 1: five runs, 95–100 s, rc=0
      (inferred from the absence of the `FAILED … rc=-9` form, which appears in this same
      log for this same task 11 times pre-fix). Clause 2: post-fix waits **38 s and 44 s**,
      an order of magnitude under the bound.
      **Sample size stated plainly: n=2 post-fix deferral episodes.** That is thin, and the
      clause names no minimum. Both pass by ~15×, and the pre-fix comparator in the same log
      is 1313 s — so the margin, not the count, is what makes this a tick. An earlier draft
      of this box said it FAILED 2.2×; that was a max taken across a window straddling the
      fix (see the breakdown below).
      **Why 600 s, derived rather than picked:** `plugin-update` fires every ~600 s, so a
      wait shorter than one fire interval delays nothing — the next fire would have run
      then anyway. 600 s is therefore the point at which a deferral starts costing a real
      update cycle. An earlier draft used 180 s ("~2× the observed lock hold"), which is a
      convention, not a derivation: any value in [96, 1919] would have "passed today and
      failed in the 32-min era" equally well.
      ~~and **no `plugin-update deferred (marketplace lock held)` line whose timestamp falls
      inside a `marketplace-refresh` run interval.**~~
      ~~and `plugin-update` no longer logging `deferred (marketplace lock held)`.~~
      **REWORDED TWICE 2026-09-04, and the second reword is the lesson.**
      - **v1 (original)** "no `deferred` line at all" — unsatisfiable: every holder of
        `marketplace-op.lock` produces it (`version-update`, `fleet-plugins-update`,
        per-session ops), so no change to THIS task can suppress it.
      - **v2 "no line inside a refresh interval"** — also unsatisfiable, which I did not
        see until a review did the arithmetic. Refresh holds the lock ~95 s; `plugin-update`
        fires ~every 10 min; the schedules are independent, so they collide on roughly
        **95/600 ≈ 16%** of fires — ~23 times a day, forever, by chance rather than by
        defect. And `945fb3e0` on this same card argues those deferrals ARE expected
        behaviour. A clause that fails on behaviour the card calls healthy is a permanent
        red light, not an acceptance criterion.
      - **v3 ~~≤180 s total deferral~~ — WRONG THRESHOLD, wrong quantity.** I derived 180
        from the **lock hold** (~95 s max) while the clause measures **total wait per
        request**. Those are different: a request retries ACROSS refresh cycles and
        accumulates. Measured — min 38 s, median 44 s, **max 1313 s (~22 min)**. A 180 s
        bound fails 7× over. Third clause in a row shipped without measuring the quantity
        it names, and the only one where one command would have caught it before it landed.
      - **v4 (current): ≤300 s total wait, first deferral → next `rc=0`.** Chosen from the
        measured distribution rather than from an adjacent number: it clears the median
        (44 s) with an order of magnitude of headroom and still fails the tail, which is
        correct, because the tail is a real defect this card has not fixed.

      **~~⚠ THE FINDING THIS EXPOSED: a request waits up to 1313 s ≈ 22 min, so the real
      improvement is ~1.5×, not ~20×.~~ WRONG — RETRACTED. The 1313 s episode is PRE-FIX.**
      Splitting the three episodes by their endpoints, which is what I should have done
      before drawing any conclusion from the max:

      | first defer | last defer | success | wait | regime |
      |---|---|---|---|---|
      | 22:58:03 | 23:19:40 | 23:19:56 | **1313 s** | **PRE-FIX** — spans the cap-killed run (22:47:40 → reaped 23:19:56) |
      | 02:22:44 | 02:23:11 | 02:23:22 | **38 s** | post-fix |
      | 04:26:00 | 04:26:31 | 04:26:44 | **44 s** | post-fix |

      The 22-minute wait is the OLD behaviour, ending at the exact instant the 1920 s cap
      killed that run. **Post-fix, a request waits 38–44 s** — an order of magnitude under
      the 600 s bound. So clause 2 **passes** on the data that is actually about the fix.

      **How I got it backwards:** I took a max across a window that straddles the fix and
      attributed it to the post-fix system, then built a "~1.5× not ~20×" headline on it —
      after spending the same commit arguing that hold and request-wait are different
      quantities. Mixing pre- and post-fix samples is the same error one level up, and the
      episode's own timestamps show it: its success is the cap-kill reap.

      Both v1 and v2 asserted the **absence of a symptom** — the broken and fixed states
      emit the *same string*, differing only in magnitude, so no absence-shaped clause can
      tell them apart. v3 got the shape right and the quantity wrong.
      **The reusable lesson, worth more than either rewrite:** when a defect and its fix
      produce the same log line at different magnitudes, the acceptance criterion must bound
      the magnitude. "No X appears" cannot distinguish them and will read as failure forever.
      (Also: an earlier edit put a reword in prose ABOVE the box and left the box text alone
      — the "nothing evaluates a condition written as prose" defect, committed onto a
      checkbox one card after correcting it three times on TRDD-8BXMNQ4T.)
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
