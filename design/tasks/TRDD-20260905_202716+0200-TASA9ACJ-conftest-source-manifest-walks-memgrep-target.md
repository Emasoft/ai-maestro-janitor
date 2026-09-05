---
trdd-id: TASA9ACJ
title: conftest source manifest walks and sorts the 100k-file memgrep target tree before filtering it out
column: dev
created: 2026-09-05T20:27:16+0200
updated: 2026-09-05T20:27:16+0200
current-owner: janitor-main-session
assignee: lean-worker
task-type: bugfix
priority: medium
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
parent-trdd: 7NSRD8OV
npt: []
eht: []
---

## Symptom

Every pytest invocation enumerates and sorts 103,910 filesystem entries twice — once in
`pytest_configure`, once in `pytest_sessionfinish` — to keep 511 of them, regardless of
which tests are selected. On a host at loadavg 133 that walk took 8–22 s per call; a single
cProfile run under external `cargo test` load attributed 54.6 s of a 63 s 19-test run to it
(`reports/board-drain/20260905_200826+0200-LDSCQ0NU-duration-investigation.md`,
`tests/conftest.py:549 _source_manifest`). The seconds are load-contaminated; the 200×
entry ratio and the pruned walk's sub-second time under the same load are not.

## Mechanism (measured 2026-09-05)

`tests/conftest.py:562` does `for p in sorted(root.rglob("*"))` and only at `:565` skips
paths with `target` or `__pycache__` in their parts. `rglob` cannot prune a directory
before descending, so the walk enumerates and stats every file under
`scripts/memgrep/target/` (5.1 GB, 101,173 files today — the docstring at `:553-554` still
says 1.4 GB / 15,285) and then sorts 103,910 `Path` objects, only to discard 99.5 % of them.

| walk | entries | wall (2 runs, loaded host) |
|---|---|---|
| `sorted(Path("scripts").rglob("*"))` | 103,910 | 22.41 s / 8.58 s |
| `os.walk` pruning `target` + `__pycache__`, `*.py`/`*.sh` only | 511 | 0.13 s / 0.24 s |

Source: `reports/board-drain/20260905_202532+0200-soak-compare-and-conftest-walk-cost.md`
(Part B). The call is guarded by `hasattr(config, "workerinput")` at `:695`, so under xdist
it runs once in the controller, not once per worker — the cost is per invocation, not per
worker. It still lands on every targeted run an agent makes while draining the board, and on
the publish gate's full run, and it competes for disk with whatever else the host is doing.

## Fix requirement

Prune the walk instead of filtering its output: iterate `os.walk(root)` and drop `target`
and `__pycache__` from `dirnames` in place before descending, collecting only `*.py` and
`*.sh` files. The manifest must be the SAME mapping the current code produces (same
relpaths, same hashes, same sorted order of insertion) — this card changes cost, not
content. Update the docstring's stale size numbers or drop them.

## Acceptance criteria

- [ ] `_source_manifest` no longer descends into any directory named `target` or
      `__pycache__` (os.walk with in-place `dirnames` pruning, or equivalent).
- [ ] A test asserts the pruned walk never visits a path under a `target` directory (e.g. a
      tmp tree with `target/deep/x.py` and `src/y.py` — the manifest contains `src/y.py`
      only, and a walk spy or a marker file inside `target/` proves it was not read).
- [ ] A test asserts the manifest for a fixture tree is identical (keys and values) to a
      hand-built dict of the expected relpath → sha256.
- [ ] Targeted run green: the test file that covers `_source_manifest`, plus
      `uv run ruff check tests/conftest.py`, `uv run mypy scripts/ --ignore-missing-imports`,
      `uvx --with pyright pyright tests/conftest.py`.
- [ ] Full suite green — deferred to the publish gate (host loadavg was 87–144 while this
      card was filed; do not start a full run to prove this box).

## Notes

Filed from the LDSCQ0NU duration investigation, which set out to prove a subprocess-timeout
hang and instead falsified it: the fake detector completed in under a second and the time was
all in this session hook. EHT of TRDD-7NSRD8OV (the flake-under-load card): a 20–45 s disk
walk at the start and end of every run is one more thing contending with the timed
subprocesses that card tracks, though it is not shown to be the cause of any specific
`TimeoutExpired`.

## Approval log
