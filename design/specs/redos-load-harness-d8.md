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
2. Step B: commit the estimator in `hooks/secret-shield/tests/load/`: `timing.ts`, the quadratic-rule fixture `old-quadratic.ts` (WHY header: known-quadratic regexes kept as a fixture; scanners may flag them) and the probe `probe.load.ts`. `claude plugin test` collects only `*.test.ts` and `*.test.tsx`, at any depth, with no filter flag, so the release gate never runs these files; a real `run_secret_shield_tests.py` run confirms its count stays 841. `tests/load/` stays inside the project tsc and eslint coverage. The probe declares its row count in a header line `// expected-rows: N`, and imports `describe` explicitly if it uses one (measured: a file that calls `describe` without importing it fails to load).
3. Step C: `tests/harness/redos_load_harness.py` (not named `test_*`, so pytest does not collect it; it ships with the plugin as test code).
4. One campaign, reported to the owner in a user-visible message at least one turn before it starts, and run only after a one-line note (duration, peak load, no request) has been sent to the local Claude sessions. An owner veto stops it.

## Harness behaviour

- Ambient check: take three 1-min load samples over 20 s; refuse (exit 3, run nothing) if the maximum is 0.7 per core or more.
- Workers: 35 CPU-only workers (2.5 per core on the 14-core dev host), started once, in one batch, under one recorded process group. Each worker exits on EOF of a pipe the harness holds (a reader thread watches it) and at its hard lifetime.
- Sampler: reads the 1-min load every 2 s in every phase; above 60 it kills and reaps the group and records the campaign as aborted (neither pass nor fail).
- Liveness: every worker is polled before and after each probe; a dead worker invalidates the campaign.
- Assembly per probe: a fresh temp dir, `assemble_plugin_dir` for the real secret-shield module, then `probe.load.ts` copied to `probe.test.ts`, then the harness appends `hooks/secret-shield/tests/load/probe.test.ts` to the expected test list that `assemble_plugin_dir` returned (that list is built before the copy).
- Probe: one `claude plugin test` run, timeout 300 s (a timeout is a probe failure).
- Timing and cap: the workers start, the load settles about 70 s, then the first probe runs as a dry run, excluded from verdicts and included in the cap. The cap is 43 min for the whole run (ambient check, settle, dry run, probes) and worker lifetime is a hard 48 min. After the dry run, K is the largest count up to 20 whose expected end, at the dry-run duration per probe, fits the cap; the dry-run duration and K are recorded. Hitting the cap records the campaign as aborted.

## Verdicts

The output prints a header line `<path>:` per file, then one line per test, `(pass) <name> [time]` or `(fail) <name> [time]`. A test inside `describe` is named `<describe> > <test>`. No file:line is printed, so tests are attributed by file header plus full name.

- Probe count: a verdict needs K = 20 non-dry-run probes, and all K count (no best-of selection). If K comes out below 20, the campaign is incomplete (neither pass nor fail), and the cap or the worker count is restated in this file before any re-run.
- Undecided rows: a mutant row whose estimator ran out of rounds is undecided, not a detection. Any undecided mutant row makes its probe undecided, and an undecided probe makes the campaign incomplete (neither pass nor fail).
- 1a: every row of `probe.test.ts` passes in each of the K = 20 non-dry-run probes, the quadratic mutant rows (detected only on a superlinear or escaped verdict) included, and the probe reported the number of rows its `expected-rows` header declares. A mutant row judged linear, or a missing probe, makes 1a NOT MET.
- TRDD-Z41A13XV: in `hooks/secret-shield/tests/patterns.test.ts`, the two tests of the describe block `a port-skip query scan is linear up to 256 KB and still tells a port from a password` (the 8x-growth test and the same-growth-then-short-password test) pass in each of the K = 20 non-dry-run probes. If increment 1b has replaced them, the replacement counts only after it has been shown red on the regex the original assert guards (the 1b mutant proof).
- Any other failing test is recorded by name as collateral and makes neither verdict pass or fail.
- The 20/20 must hold wherever a probe lands (performance or efficiency core).

## Records

One JSON line per probe in `reports_dev/redos-load-harness/`: exit code, pass and fail counts, the 1a rows, the Z41A13XV tests, collateral failures, load at start and end, ambient estimate, dry-run flag.

## Tests

Pure tests for the worker-count formula and the ambient refusal; an abort test that feeds the sampler a reading of 61 while real workers run and asserts each recorded PID is reaped (`kill(pid, 0)` raises after `waitpid`); an orphan test that SIGKILLs the harness and asserts the workers exit within a few seconds; a smoke run (K=1, N=2) under the `integration` marker, skipped without `claude`, which proves only that the harness runs end to end.

## Step C additions (reviews of c6e06bb4 and bbe8bbf4)

- Files step C may touch: `tests/harness/redos_load_harness.py`, its pytest file, the import-existence pytest, one comment line in `scripts/run_secret_shield_tests.py`, and, only if the probe does not expose a mutant row's verdict reason, `hooks/secret-shield/tests/load/probe.load.ts` and `timing.ts`. Any change to those two repeats the step B checks: the gate still runs 841, and an idle assembly shows all rows under the probe.
- The probe copy goes in the same directory inside the temp assembly: `hooks/secret-shield/tests/load/probe.test.ts`, relative to the temp dir, the same form `assemble_plugin_dir` returns.
- A fresh temp dir per probe (`assemble_plugin_dir` raises on a non-empty one).
- Two probe checks: the file header proves the probe was collected; the row check proves all rows ran. The row check asserts the counts per kind, 6 linear rows (L1, L1c, L2d, L3, L3b, L3c) and 7 mutant rows (Q1, Q2, Q2b, Q3, Q4, Q5, Q6), or their names, not only the `expected-rows` total.
- An import-existence pytest: every name that `probe.load.ts`, `old-quadratic.ts` and `timing.ts` import from `../../patterns` and `../../rules/*` still exists as an export in those files (plain text check). No TypeScript checker covers `hooks/`, and the release gate never loads these files, so this is the only guard between releases.
- One WHY line in `scripts/run_secret_shield_tests.py` naming `tests/load/*.load.ts` as deliberately uncollected.
- The CPV check of the shipped quadratic fixture is tracked on TRDD-KADV0ZO6 (the first real publish run).
- The step B files were copied verbatim from the scratch versions used in the idle 1a runs (25 of 25); the main agent did not reread them line by line.

## Step C additions (review of b93025a7)

- Each test line shows only (pass) or (fail), so the probe must expose each mutant row's verdict reason (linear, superlinear, escaped, or out of rounds), in the test name or a stdout line; step C makes that edit to `probe.load.ts`, with the step B re-checks. A mutant (fail) whose reason cannot be read makes the probe invalid, not a 1a failure.
- A linear row that runs out of rounds is a failure of 1a, not undecided: a false failure of a linear rule under contention is what the campaign measures.
- The per-probe JSON line records the number of undecided rows. If a campaign ends incomplete because of undecided rows, the remedy is a larger round budget for mutant rows, restated in this file, never re-running until 20 probes come out clean.

## Step C split and gate safety (review of the first step C brief)

- Step C is two commits. C1, the reason mechanism: measure whether `claude plugin test` passes a test's console output through to its own output (scratch plugin); give `timing.ts` a distinct out-of-rounds outcome that it returns rather than leaves to be inferred (the one permitted estimator change); make `probe.load.ts` report each mutant row's reason by console output if it passes through, else by a file in the temp assembly that the harness reads; repeat the step B checks. C2: the harness and its tests.
- Tests that start real workers or call `claude` run only when the environment variable `REDOS_HARNESS_REAL=1` is set and skip otherwise, so the default pytest run and `publish.py` never run them (`pyproject.toml` deselects no marker by default). Only the pure tests and the import-existence check run in the release gate.
- Worker lifetime is a harness parameter (default 48 min); tests use about 30 s. Every test that starts workers kills the recorded process group in a `finally` and then asserts each PID is gone, whatever the outcome.
- Exit code 2 covers aborted, incomplete and invalid; the JSON record names which.

## Reason channel and safety-test owner (review of 52c0e1e0)

- The probe reports a reason line for every row, linear and mutant, through a sandbox-legal channel only: console output if it passes through for passing tests too; else an `expect` failure message if the runner prints it; else test names generated at load time from verdicts computed before `test()` is registered. A file written from inside the plugin test sandbox is not an option (the sandbox refuses `node:fs`), and the sandbox is never worked around. If no channel works, C1 stops, changes nothing, and reports.
- At idle the probe shows 0 out-of-rounds results and the same linear and superlinear decisions as before C1.
- Who runs the real-process tests: the campaign procedure runs every `REDOS_HARNESS_REAL=1` test immediately before each campaign, and all must pass; a failure means no campaign. C2's report includes one such run.

## Reason channel correction (review of bb0aeaa9)

- This section replaces the channel list in the section above. The `expect` failure message is not a channel: it prints only for failing rows, so passing rows would carry no reason. The legal order is console output (only if it passes through for passing tests), else test names generated at load time, else C1 stops and changes nothing.
- With load-time names the 13 measurements run at module load (collection), not inside `test()`. Each row's measurement is wrapped so an exception becomes that row's verdict `error` rather than a failed file load; C1's report states that the measurement moved; the idle re-check confirms 13 named rows and 0 out-of-rounds.
- Before C1 is committed, its diff is checked for `node:fs`, `writeFile` and `redos-rows.txt`.
