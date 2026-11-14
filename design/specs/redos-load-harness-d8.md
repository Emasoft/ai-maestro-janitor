---
title: ReDoS load harness, ruling D8 consolidated
status: normative
trdd: [OD5Z90YL, Z41A13XV]
created: 2026-11-14T07:50:00+0100
updated: 2026-11-14T08:30:00+0100
---

# ReDoS load harness (ruling D8, consolidated)

This file is the single current spec for the load harness of TRDD-OD5Z90YL. It supersedes the D8 ruling, its amendments and clarifications written as dated notes on that card on 2026-11-14, and every earlier version of this file; git keeps that history. Decided by the main agent under the owner mandate TRDD-S6GX1DHN after review; the owner may veto any part.

## Purpose

Show that the secret-shield timing checks hold under steady CPU contention. Contention, not the 1-min load average, is the controlled variable: the average lags about 60 s and is moved by other sessions on the host, which made two ramp-steered scratch runs overshoot (to 90 the second time).

## Build order

Each step is its own commit, verified before the next.

1. Step A, done in 272b6420: `assemble_plugin_dir(tmp, mod, mod_dir)` in `scripts/run_secret_shield_tests.py`, shared by the release gate and the harness. `tmp` must be an empty directory; the function returns the expected test files relative to `tmp`, built before any later copy.
2. Step B, done in bbe8bbf4: the estimator in `hooks/secret-shield/tests/load/`: `timing.ts`, the quadratic-rule fixture `old-quadratic.ts` (WHY header) and the probe `probe.load.ts` with a first line `// expected-rows: 13`. `claude plugin test` collects only `*.test.ts` and `*.test.tsx`, at any depth, with no filter flag, so the release gate never runs these files (its count stays 841). A test file that calls `describe` must import it. No TypeScript checker covers `hooks/`. The files were copied verbatim from the scratch versions used in the idle 1a runs (25 of 25) and were not reread line by line.
3. Step C1, the reason channel. Files: `timing.ts` and `probe.load.ts` only.
   - `timing.ts` ends in one of four verdicts: `linear` (confirmed under the limit), `escaped` (timing.ts:9-10 and :39: the big run stayed under ESCAPE_MS even at SIZE_CAP, too fast to time; it proves nothing and is never a pass), and, when its rounds are exhausted without a decision, `superlinear` if the last cumulative-minimum ratio is at or over the limit, or `out-of-rounds` if it is under the limit but unconfirmed. `judge()` never returns `superlinear` itself, so a mutant detection means "never confirmed linear, and the last ratio over the limit". Before C1 every exhausted run was `superlinear`; splitting off `out-of-rounds` is the one permitted estimator change (done in b3ca0fc5).
   - Measure whether `claude plugin test` passes a test's console output through to its own output for passing tests as well as failing ones.
   - The probe reports one line per row, linear and mutant, `REDOS-ROW <id> <linear|mutant> <verdict>`, through a sandbox-legal channel only, in this order: console output if it passes through for passing tests; otherwise test names generated at load time. With load-time names the 13 measurements run at module load (collection), each wrapped so an exception becomes that row's verdict `error` rather than a failed file load, and the report states that the measurement moved. A failure message is not a channel (it prints only for failing rows). A file written from inside the plugin test sandbox is not an option (the sandbox refuses `node:fs`), and the sandbox is never worked around. If no channel works, C1 stops, changes nothing, and reports.
   - Checks: the gate still runs 841; an idle assembly shows 13 rows under the probe, 13 reason lines, 6 linear and 7 superlinear verdicts, 0 out-of-rounds. Before commit, the main agent greps the diff for `node:fs`, `writeFile` and `redos-rows.txt` itself.
4. Step C2, the harness: `tests/harness/redos_load_harness.py` (not named `test_*`, so pytest does not collect it; it ships with the plugin as test code), its pytest file, an import-existence pytest, and one WHY line in `scripts/run_secret_shield_tests.py` naming `tests/load/*.load.ts` as deliberately uncollected.
5. One campaign. It runs only after: an idle assembly immediately before it shows 13 rows, the 6 linear rows `linear` and the 7 mutant rows `superlinear` (if not: a row count other than 13 means the probe is broken, an escaped row takes the escaped remedy, a mutant out of rounds takes the larger mutant round budget, and a linear row superlinear or out of rounds at idle is a fixture or rule defect to fix first; no campaign until a clean idle run); every `REDOS_HARNESS_REAL=1` test has passed immediately before it (a failure means no campaign); the campaign was reported to the owner in a user-visible message at least one turn earlier (acknowledgement not required; a veto stops it); a one-line note (duration, peak load, no request) went to the local Claude sessions.

## Harness behaviour

- Ambient check: take three 1-min load samples over 20 s; refuse (exit 3, run nothing) if the maximum is 0.7 per core or more.
- Workers: 35 CPU-only workers (2.5 per core on the 14-core dev host), started once, in one batch, under one recorded process group. Each worker exits on EOF of a stdin pipe the harness holds (a reader thread watches it) and at its lifetime, a parameter defaulting to 48 min.
- Sampler: reads the 1-min load every 2 s in every phase, from an injectable source; above 60 it kills and reaps the group and records the campaign as aborted.
- Liveness: every worker is polled before and after each probe; a dead worker invalidates the campaign.
- Assembly per probe: a fresh temp dir; `assemble_plugin_dir` for the real secret-shield module; `probe.load.ts` copied to `probe.test.ts` in the same directory inside the assembly; `hooks/secret-shield/tests/load/probe.test.ts` appended to the expected list.
- Probe: one `claude plugin test` run in its own session, timeout 300 s (a timeout is a probe failure).
- Timing and cap: the workers start, the load settles about 70 s, then the first probe runs as a dry run, excluded from verdicts and included in the cap. The cap is 43 min for the whole run (ambient check, settle, dry run, probes); worker lifetime 48 min. After the dry run, K is the largest count up to 20 whose expected end, at the dry-run duration per probe, fits the cap; the dry-run duration and K are recorded. Hitting the cap records the campaign as aborted.
- Exit codes: 0 pass, 1 fail, 2 aborted, incomplete or invalid (the record names which), 3 refused.

## Verdicts

The output prints a header line `<path>:` per file, then one line per test, `(pass) <name> [time]` or `(fail) <name> [time]`. A test inside `describe` is named `<describe> > <test>`. No file:line is printed, so tests are attributed by file header plus full name; row reasons come from the C1 channel.

- Probe count: a verdict needs K = 20 non-dry-run probes, and all K count (no best-of selection). If K comes out below 20, the campaign is incomplete, and the cap or the worker count is restated in this file before any re-run.
- Probe validity: a probe is invalid if `probe.test.ts` has no header, if its rows differ from the declared count or from 6 linear (L1, L1c, L2d, L3, L3b, L3c) and 7 mutant (Q1, Q2, Q2b, Q3, Q4, Q5, Q6), if any row's reason cannot be read, or if any row's verdict is `error` (an exception means the probe is broken, not that the estimator decided). An invalid probe makes the campaign invalid.
- Mutant rows: detected only on a superlinear verdict (as defined in step C1: exhausted, never confirmed linear, last ratio at or over the limit). The probe prints the ids L1, L1c, L2d, L3, L3b, L3c, Q1, Q2, Q2b, Q3, Q4, Q5, Q6 exactly (checked against probe.load.ts). A mutant row judged linear makes 1a NOT MET. A mutant row out of rounds is undecided; an undecided probe makes the campaign incomplete, and the remedy is a larger round budget for mutant rows, restated in this file, never re-running until 20 probes come out clean.
- Linear rows: pass only on a linear verdict. Under load, a linear row judged superlinear or out of rounds is a 1a failure (an escaped linear row is undecided, below): a false failure of a linear rule under contention is what the campaign measures. The same verdict at idle is not a measurement: it blocks the campaign under step 5.
- Escaped rows: a row of either kind whose verdict is `escaped` (too fast to time) makes its probe undecided, and so the campaign incomplete; it is never a pass and never a 1a failure. Its remedy is raising SIZE_CAP or replacing that row's fixture, recorded in this spec with its new value, never re-running until clean.
- Rows are judged from their REDOS-ROW verdicts, not from the probe test's (pass) or (fail): a mutant row out of rounds or escaped, and an escaped linear row, fail their tests by design and are still undecided. A probe with a missing, duplicate or unknown REDOS-ROW id is invalid (exit 2). The test outcome of each row is still recorded in the per-probe record.
- 1a is met when every row passes in each of the K = 20 non-dry-run probes and no probe is invalid or undecided.
- TRDD-Z41A13XV: in `hooks/secret-shield/tests/patterns.test.ts`, the two tests of the describe block `a port-skip query scan is linear up to 256 KB and still tells a port from a password` (the 8x-growth test and the same-growth-then-short-password test) pass in each of the K = 20 non-dry-run probes. If increment 1b has replaced them, the replacement counts only after it has been shown red on the regex the original assert guards.
- Any other failing test is recorded by name as collateral and makes neither verdict pass or fail.
- The 20/20 must hold wherever a probe lands (performance or efficiency core).

## Records

One JSON line per probe in `reports_dev/redos-load-harness/`: exit code, pass and fail counts, each row with its verdict and its test outcome, the Z41A13XV tests, collateral failures, undecided count, invalid reason if any, load at start and end, ambient estimate, dry-run flag.

## Tests

- In the release gate (default pytest run): pure tests for the worker-count formula, the ambient refusal and the verdict rules; an import-existence test that every name `probe.load.ts`, `old-quadratic.ts` and `timing.ts` import from `../../patterns` and `../../rules/*` still exists as an export there (plain text check, the only guard between releases).
- Only with `REDOS_HARNESS_REAL=1` (skipped otherwise, because `pyproject.toml` deselects no marker): an abort test that feeds the sampler a reading of 61 while real workers run and asserts each recorded PID is reaped (`waitpid`, then `kill(pid, 0)` raises); an orphan test that SIGKILLs the harness in a workers-only mode and asserts its workers exit within 10 s; a smoke run (K=1, N=2) that proves only that the harness runs end to end, skipped without `claude`. These tests use a worker lifetime of about 30 s and kill the recorded process group in a `finally`, then assert every PID is gone, whatever the outcome. C2's report includes one such run.
- No test runs the full 35-worker campaign.

## Elsewhere

The CPV check of the shipped quadratic fixture before the first real publish is tracked on TRDD-KADV0ZO6.
