---
trdd-id: NLHVLGEP
title: The runaway alarm can report ground truth by differencing cumulative CPU time across its own two fires
column: backburner
created: 2026-08-20T18:05:19+0200
updated: 2026-08-20T18:05:19+0200
current-owner: janitor-main-session
task-type: feature
priority: normal
approval-tier: 0
scope: project
external-refs: [TRDD-JEEQCHFG, TRDD-8QSLYMGU]
npt: []
eht: []
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

- [ ] Two consecutive fires with a known time delta produce a differenced figure that
      matches an independently computed burn (real `ps`, no fake rows)
- [ ] A first-ever fire, and an entry migrated from the old schema, both report the
      estimator wording and never crash
- [ ] pid+command key still governs; a recycled pid cannot inherit a predecessor's `time`
      (a smaller `time` than stored ⇒ treat as a new process, report no delta)
- [ ] thresholds and `min_streak` unchanged, grep-proven
- [ ] pytest, ruff, mypy, pyright clean

## Approval log
