---
trdd-id: NLHVLGEP
title: The runaway alarm can report ground truth by differencing cumulative CPU time across its own two fires
column: complete
created: 2026-08-20T18:05:19+0200
updated: 2026-10-09T23:22:36+0200
current-owner: janitor-main-session
task-type: feature
priority: normal
scope: project
external-refs: [TRDD-JEEQCHFG, TRDD-8QSLYMGU]
npt: []
eht: []
min-approval-requirement: none
implementation-commits: [ac63bb09, b175178f, c5be7275]
status: archived
---

# Report the measured burn, not an estimate of it

## Why

TRDD-JEEQCHFG cost four sessions an evening arguing about what `ps %cpu` means, and the
argument was possible only because the alarm reported a number whose window it did not
state. The 2026-08-20 measurement settled it — `%cpu` is a good estimator at the detector's
600 s cadence (median error +1.9 points, stdev 5.1) — but "good estimator" is a fact a
reader has to be told, whereas a measured interval needs no defending.

The detector is already one field away from the measured version. It fires ~every 600 s, it
already persists a per-key streak map (`sustained_findings`, keyed on pid AND command), and
`ps` already yields cumulative CPU `time`. Storing that `time` alongside the streak lets the
second fire compute `(time₁ − time₀) / (t₁ − t₀)` — ground truth over exactly the window the
alarm spans, which is also exactly the window the streak gate already requires.

## What

1. Extend the persisted streak entry to carry `(streak, cpu_time_s, sampled_at_epoch)`.
   Migration must be forward-only and fail-open: an old entry with no time field yields no
   differenced number, not a crash and not a dropped finding.
2. When both samples are present, `format_drift_line` reports the measured burn and its
   window — e.g. `287% sustained over the last 612s (measured)` — and falls back to today's
   `%cpu` wording (with its "~1-minute decaying average" caveat) when they are not.
3. Do NOT change `cpu_threshold_pct`, and do NOT remove the streak gate: JEEQCHFG's
   measurement says the current values are right and the gate is what absorbs single-sample
   noise (p95 +57.5 points at a 60 s window).
4. The differenced value is for the REPORT. Gating on it is a separate decision with its own
   evidence — do not smuggle it in here.

## Acceptance

- [x] Two consecutive fires with a known time delta produce a differenced figure that
      matches an independently computed burn (real `ps`, no fake rows)
- [x] A first-ever fire, and an entry migrated from the old schema, both report the
      estimator wording and never crash
- [x] pid+command key still governs; a recycled pid cannot inherit a predecessor's `time`
      (a smaller `time` than stored ⇒ treat as a new process, report no delta)
- [x] thresholds and `min_streak` unchanged, grep-proven
- [x] pytest, ruff, mypy, pyright clean

## Approval log
- 2026-10-07T08:45:10+0200 — column → testing by main-agent@ai-maestro-janitor. B7 merged and gated at b175178f
2026-10-09 CLOSED by the main session (board drain, wave 3). Boxes ticked on tests in tests/test_runaway_measured_burn.py (11 passed today): box 1 test_two_fires_with_a_known_cpu_delta_give_the_computed_burn and test_detector_reports_measured_burn_on_the_second_fire_of_a_real_busy_process; box 2 test_no_measured_entry_keeps_the_estimator_wording and test_old_schema_or_junk_entry_gives_no_delta; box 3 test_recycled_pid_with_smaller_cpu_time_gives_no_delta; box 4 test_trigger_thresholds_are_unchanged, and the diff ac63bb09^..c5be7275 of scripts/lib/daemon_runaway.py changes no threshold or streak line; box 5 the full gate of 2026-10-09. Fix commits are ancestors of the v3.8.11 tag. Field, the card's own case: this session's heartbeat of 2026-10-09 printed a system-daemon-runaway line reading 'CPU 99% (measured over the last 618s from CPU time; over the bar on 2 consecutive checks)'; seen on heartbeat stdout, not located in a log file. Open follow-up stays as the card records it: a recycled pid with MORE cpu time. Assessment: reports/board/20261009_232136+0200-wave3-batchE.md.
- 2026-10-09T23:22:36+0200 — COMPLETE by main-agent@ai-maestro-janitor. released in v3.8.11; tests re-run; see Approval log 2026-10-09.

## Implementation notes

2026-10-07: the runaway alarm states burn measured between two fires from CPU time; thresholds unchanged and pinned by a test; follow-up: a recycled pid with MORE CPU time than the stored sample gives a wrong figure (guard by storing the process start time); the figure only appears in the alarm text, it never triggers it.
2026-10-07: shipped in v3.8.5; release observation starts.
2026-10-07: the end-to-end test was load-dependent (it blocked the first 3.8.5 publish attempt at load 112); c5be7275 checks the figure against the busy child's own CPU time instead.
