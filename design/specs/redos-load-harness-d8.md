---
title: ReDoS load harness, ruling D8 consolidated
status: normative
trdd: [OD5Z90YL, Z41A13XV]
created: 2026-11-14T07:50:00+0100
updated: 2026-11-14T07:50:00+0100
---

# ReDoS load harness (ruling D8, consolidated)

This file is the single current spec for the load harness of TRDD-OD5Z90YL. It supersedes the D8 ruling, its amendments 1 to 3 and the clarifications written as dated notes on that card on 2026-11-14; those notes stay as history. Decided by the main agent under the owner mandate TRDD-S6GX1DHN after review; the owner may veto any part.

## Purpose

Show that the secret-shield timing checks hold under steady CPU contention. Contention, not the 1-min load average, is the controlled variable: the average lags about 60 s and is moved by other sessions on the host, which made two ramp-steered scratch runs overshoot (to 90 the second time).

## Build order

1. Step A, done in 272b6420: `assemble_plugin_dir(tmp, mod, mod_dir)` in `scripts/run_secret_shield_tests.py`, shared by the release gate and the harness. `tmp` must be an empty directory.
2. Step B: commit the estimator in `hooks/secret-shield/tests/load/`: `timing.ts`, the quadratic-rule fixture `old-quadratic.ts` (WHY header: known-quadratic regexes kept as a fixture; scanners may flag them) and the probe `probe.load.ts`. `claude plugin test` collects only `*.test.ts` and `*.test.tsx`, at any depth, with no filter flag, so the release gate never runs these files; a real `run_secret_shield_tests.py` run confirms its count stays 841. `tests/load/` stays inside the project tsc and eslint coverage. The probe declares its row count in a header line `// expected-rows: N`.
3. Step C: `tests/harness/redos_load_harness.py` (not named `test_*`, so pytest does not collect it; it ships with the plugin as test code).
4. One campaign, reported to the owner in a user-visible message at least one turn before it starts, and run only after a one-line note (duration, peak load, no request) has been sent to the local Claude sessions. An owner veto stops it.

## Harness behaviour

- Ambient check: take three 1-min load samples over 20 s; refuse (exit 3, run nothing) if the maximum is 0.7 per core or more.
- Workers: 35 CPU-only workers (2.5 per core on the 14-core dev host), started once, in one batch, under one recorded process group. Each worker exits on EOF of a pipe the harness holds (a reader thread watches it) and at its hard lifetime.
- Sampler: reads the 1-min load every 2 s in every phase; above 60 it kills and reaps the group and records the campaign as aborted (neither pass nor fail).
- Liveness: every worker is polled before and after each probe; a dead worker invalidates the campaign.
- Assembly per probe: a fresh temp dir, `assemble_plugin_dir` for the real secret-shield module, then `probe.load.ts` copied to `probe.test.ts`, then the expected test list is rebuilt so it includes the probe.
- Probe: one `claude plugin test` run, timeout 300 s (a timeout is a probe failure).
- Timing and cap: the workers start, the load settles about 70 s, then the first probe runs as a dry run, excluded from verdicts and included in the cap. The cap is 43 min for the whole run (ambient check, settle, dry run, probes) and worker lifetime is a hard 48 min. After the dry run, K is the largest count up to 20 whose expected end, at the dry-run duration per probe, fits the cap; the dry-run duration and K are recorded. Hitting the cap records the campaign as aborted.

## Verdicts

The output prints a header line `<path>:` per file, then one line per test, `(pass) <name> [time]` or `(fail) <name> [time]`. A test inside `describe` is named `<describe> > <test>`. No file:line is printed, so tests are attributed by file header plus full name.

- 1a: every row of `probe.test.ts` passes in every probe, the quadratic mutant rows (which assert non-linear) included, and the probe reported the number of rows its `expected-rows` header declares. A mutant row that stays linear, or a missing probe, makes 1a NOT MET.
- TRDD-Z41A13XV: in `hooks/secret-shield/tests/patterns.test.ts`, the two tests of the describe block `a port-skip query scan is linear up to 256 KB and still tells a port from a password` (the 8x-growth test and the same-growth-then-short-password test), or the check that replaces them in increment 1b, pass in every probe.
- Any other failing test is recorded by name as collateral and makes neither verdict pass or fail.
- The 20/20 must hold wherever a probe lands (performance or efficiency core).

## Records

One JSON line per probe in `reports_dev/redos-load-harness/`: exit code, pass and fail counts, the 1a rows, the Z41A13XV tests, collateral failures, load at start and end, ambient estimate, dry-run flag.

## Tests

Pure tests for the worker-count formula and the ambient refusal; an abort test that feeds the sampler a reading of 61 while real workers run and asserts each recorded PID is reaped (`kill(pid, 0)` raises after `waitpid`); an orphan test that SIGKILLs the harness and asserts the workers exit within a few seconds; a smoke run (K=1, N=2) under the `integration` marker, skipped without `claude`, which proves only that the harness runs end to end.
