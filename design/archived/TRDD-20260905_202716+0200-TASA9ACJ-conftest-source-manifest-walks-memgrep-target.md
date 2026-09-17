---
trdd-id: TASA9ACJ
title: conftest source manifest walks and sorts the 100k-file memgrep target tree before filtering it out
column: complete
created: 2026-09-05T20:27:16+0200
updated: 2026-09-17T05:51:26+0200
current-owner: janitor-main-session
assignee: janitor-main-session
task-type: bugfix
priority: medium
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
parent-trdd: 7NSRD8OV
npt: []
eht: []
implementation-commits: [0f2edc79]
---

## Symptom

Every pytest invocation enumerates and sorts 103,910 filesystem entries twice — once in
`pytest_configure`, once in `pytest_sessionfinish` — to keep 511 of them, regardless of
which tests are selected. On a host at loadavg 133 that walk took 8–22 s per call; a single
cProfile run under external `cargo test` load attributed 54.6 s of a 63 s 19-test run to it
(`reports/board-drain/20260905_200826+0200-LDSCQ0NU-duration-investigation.md`,
`tests/conftest.py::_source_manifest`). The seconds are load-contaminated; the 200×
entry ratio and the pruned walk's sub-second time under the same load are not.

## Mechanism (measured 2026-09-05)

Before this card, `tests/conftest.py::_source_manifest` did `for p in sorted(root.rglob("*"))`
and only inside the loop skipped paths with `target` or `__pycache__` in their parts.
`rglob` cannot prune a directory before descending, so the walk enumerated and stat'ed
every file under `scripts/memgrep/target/` (5.1 GB, 101,173 files today — the docstring
still said 1.4 GB / 15,285) and then sorted 103,910 `Path` objects, only to discard 99.5 %
of them.

| walk | entries | wall (2 runs, loaded host) |
|---|---|---|
| `sorted(Path("scripts").rglob("*"))` | 103,910 | 22.41 s / 8.58 s |
| `os.walk` pruning `target` + `__pycache__`, `*.py`/`*.sh` only | 511 | 0.13 s / 0.24 s |

Source: `reports/board-drain/20260905_202532+0200-soak-compare-and-conftest-walk-cost.md`
(Part B). The call sits inside `pytest_configure`'s `if not hasattr(config, "workerinput")`
block (verified first-hand), so under xdist it runs once in the controller, not once per
worker — the cost is per invocation, not per worker. It still lands on every targeted run an agent makes while draining the board, and on
the publish gate's full run, and it competes for disk with whatever else the host is doing.

## Fix requirement

Prune the walk instead of filtering its output: iterate `os.walk(root)` and drop `target`
and `__pycache__` from `dirnames` in place before descending, collecting only `*.py` and
`*.sh` files. The manifest must be the SAME mapping the current code produces (same
relpaths, same hashes, same sorted order of insertion) — this card changes cost, not
content. Update the docstring's stale size numbers or drop them.

## ⏵ STATE — 2026-09-05 20:36 — fix landed, targeted checks green, full-suite box waits for the publish gate

`tests/conftest.py::_source_manifest` now walks with `os.walk`, pruning `target` and
`__pycache__` from `dirnames` in place, collects `*.py`/`*.sh` and sorts the candidates
once (same keys, same hashes, same insertion order as before — diff read in full by the
coordinator). Two tests in `tests/test_conftest_source_manifest.py`: hand-built-dict
equality, and an `os.walk` spy proving no yielded dirpath falls under `target/` or
`__pycache__/`. Worker's verbatim gate output in
`reports/board-drain/20260905_203019+0200-TASA9ACJ-conftest-walk-prune.md`: `2 passed`,
ruff clean, mypy `no issues found in 504 source files`, pyright `0 errors` (re-run by the
coordinator on the test file: `0 errors`). Targeted timing on `tests/test_dispatch_defang.py`:
`19 passed in 20.39s` before, `1.83s` after — ONE run each on a host at loadavg 55–145
with other pytest sessions live, so a direction, not a ratio (git-stash isolated on
`tests/conftest.py` only; stash list and the other agents' diffs verified intact
afterwards). Landed in `0f2edc79`. Remaining box: the full suite, at the publish gate.
`testing` per the JDIJ76SW / LDSCQ0NU pattern (one open box, the gate is the tester);
TRDD-5OR85VHP owns whether that pattern becomes `blocked` + `unblock-when:`.

Review-fork follow-up (same day): the old and new walks are NOT identical for every tree,
and the docstring now says so. (1) `os.walk` does not follow directory symlinks, `rglob`
does. Not following is BY DESIGN for a clobber guard (an in-repo symlink is hashed at its
real path; an out-of-repo one is foreign source and the same unbounded-tree cost class).
On the real `scripts/` tree the question is moot: `find scripts -type l -not -path
'*/target/*'` lists nothing, and the old-vs-new key lists are `511 511 True` with empty
`only-old` / `only-new`. (2) The old `"target" in p.parts` tested the ABSOLUTE path, so a
checkout under an ancestor named `target` got an empty manifest and a silently disabled
guard; the new prune is descendant-only, which is the correct direction. (3) The worker
dropped `is_file()`; restored — `filenames` can carry a FIFO, and `read_bytes()` on one
with no writer blocks in `open()`, so `pytest_configure` would hang rather than skip it.
That branch has no test on purpose: a FIFO fixture hangs on regression instead of
failing, and a dangling symlink is skipped by both forms, so any such test passes by
construction. (4) The walk-spy test now asserts `visited_dirpaths` is non-empty first —
before that, a revert to `rglob` left the list empty and the prune assertions vacuous.

## Acceptance criteria

- [x] `_source_manifest` no longer descends into any directory named `target` or
      `__pycache__` (os.walk with in-place `dirnames` pruning, or equivalent).
- [x] A test asserts the pruned walk never visits a path under a `target` directory (e.g. a
      tmp tree with `target/deep/x.py` and `src/y.py` — the manifest contains `src/y.py`
      only, and a walk spy or a marker file inside `target/` proves it was not read).
- [x] A test asserts the manifest for a fixture tree is identical (keys and values) to a
      hand-built dict of the expected relpath → sha256.
- [x] Targeted run green: the test file that covers `_source_manifest`, plus
      `uv run ruff check tests/conftest.py`, `uv run mypy scripts/ --ignore-missing-imports`,
      `uvx --with pyright pyright tests/conftest.py`.
- [x] Full suite green — deferred to the publish gate (host loadavg was 87–144 while this
      card was filed; do not start a full run to prove this box).

## Notes

Filed from the LDSCQ0NU duration investigation, which set out to prove a subprocess-timeout
hang and instead falsified it: the fake detector completed in under a second and the time was
all in this session hook. EHT of TRDD-7NSRD8OV (the flake-under-load card): a 20–45 s disk
walk at the start and end of every run is one more thing contending with the timed
subprocesses that card tracks, though it is not shown to be the cause of any specific
`TimeoutExpired`.

## Approval log
- 2026-09-16T12:33:54+0200 — column → todo. no session working it for 7-13 days while column claimed testing; re-columned honest (triage 2026-09-16)
2026-09-17 full unscoped suite on HEAD: 16804 passed, 2 skipped (reports/board-drain/20260917_baseline-gates.txt); ruff/mypy/pyright clean. — closer batch 2, approved by main session (owner standing permission 2026-09-03).
- 2026-09-17T05:51:26+0200 — COMPLETE by main session (owner standing permission 2026-09-03). Full unscoped suite on HEAD today 16804 passed/2 skipped, ruff/mypy/pyright clean (20260917_baseline-gates.txt); publish-gate criterion satisfied..
