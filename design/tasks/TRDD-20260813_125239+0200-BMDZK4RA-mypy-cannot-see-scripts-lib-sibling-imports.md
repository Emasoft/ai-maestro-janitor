---
trdd-id: BMDZK4RA
title: The mypy gate cannot see cross-module calls between scripts/lib siblings
column: complete
created: 2026-08-13T12:52:39+0200
updated: 2026-08-13T13:14:00+0200
implementation-commits: [a08d14fd, a25f706e]
current-owner: unassigned
task-type: infra
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
---

# `import state` from a `scripts/lib/` sibling is `Any` to mypy — so the gate checks nothing about it

## ⚠ RESOLVED SAME DAY — and the card's own premise was WRONG (2026-08-13 ~13:1x)

**Do not read the options below as live.** Within the hour I wrote them I checked `ci.yml` and
found the thing the card assumed was missing:

```
.github/workflows/ci.yml:46:  run: uvx --with pyright pyright scripts/     # no continue-on-error
```

**pyright is already a BLOCKING CI gate**, with `scripts/lib` in `extraPaths` and
`reportMissingImports: error`. So option 1's stated cost — *"the CI gate and the IDE disagree
permanently, and CI is the one that blocks a publish"* — is **false**. There is no divergence to
live with: the checker that sees this class runs in CI and blocks. The blind spot is real in
mypy and already covered.

**DECISION: option 1**, on corrected grounds — not "accept a gap", but "the gap is already
owned by the other checker, by design". Recorded in `pyproject.toml` beside `mypy_path`, which
is where a future session goes to 'fix' this and would otherwise re-derive the whole card.

**What the check also caught, which is the part that mattered.** Running the CI command locally
showed CI Lint was **RED**, and by my own hand: `e3422397` imported `tests/_fake_secrets` via a
runtime `sys.path.insert`, which pyright could not resolve. Fixed in `a25f706e` by adding
`tests` to extraPaths (resolving the import, not suppressing the diagnostic). So the honest
summary is the inverse of the card's title: mypy's blind spot cost one annotation mismatch,
while **my local mypy+ruff habit hid a genuine red CI job** — the checker I was not running was
the one telling the truth.

**Lesson (recorded, because it is the third instance today).** I filed a card asserting a gap
without first checking whether something already covered it. The measurement that would have
refuted it — reading `ci.yml` — was one grep away and came *after* the card was written and
committed. Same shape as the fence-mask and base64-floor errors: a conclusion published before
the population that could contradict it was consulted.

## ⏵ STATE — the original analysis (mechanism still correct, framing superseded above)

**Found while verifying a subagent's returned work, and PROVEN by controlled probe rather than
inferred.** The project's own type gate is green and honest about what it checks; it simply does
not check this class of call at all.

### The proof (same file, same mypy, only the search path differs)

```
uv run mypy scripts/lib/fleet_scan.py                      -> Success: no issues found
MYPYPATH=$PWD/scripts/lib uv run mypy scripts/lib/fleet_scan.py
   -> fleet_scan.py:784: error: Argument 1 to "atomic_write" has incompatible type "str"; expected "Path"
   -> fleet_scan.py:807: error: (same)
```

### The mechanism, verified by inspection

- `state.py` lives at `scripts/lib/state.py`, so under `mypy_path = "scripts"` it is importable
  as `lib.state` — **not** as `state`. `scripts/state.py` does not exist.
- Every `scripts/lib/` module nonetheless imports its siblings **bare** (`import state`), because
  the hooks/detectors put `scripts/lib` on `sys.path` at RUNTIME.
- `ignore_missing_imports = true` then silently degrades that unresolved import to `Any`, so
  every attribute access on it type-checks vacuously.
- **pyright resolves it** (its `include` covers `scripts`), which is why the IDE reports errors
  the gate does not.

The stale premise is recorded in `pyproject.toml`'s own comment: it says the detectors import as
`from lib import <submodule>`. That convention is not what the tree does — the bare form is
pervasive, and the two conventions are already a known trap
(wikimem: `janitor-hooks-two-import-conventions`).

### What is NOT wrong — do not "fix" these

- **The gate is green and correct for what it runs.** `uv run mypy scripts/ --ignore-missing-imports`
  (publish.py G2d / ci.yml parity) → `Success: no issues found in 477 source files`. A tree-wide
  `mypy scripts tests` shows ~57 errors, but **79 of those lines are `tests/`**, which the gate
  deliberately does not check. Do not "discover" that number and report the gate as broken.
- **The two `atomic_write` findings were never a runtime bug.** Its body's FIRST line is
  `target = Path(target)` — it has always normalized. The annotation was merely untrue of the
  contract; widened to `Path | str` in this card's commit, which makes the strict view clean by
  RESOLVING the mismatch, not by suppressing it.

### The naive fix does not work — measured, not assumed

Adding `scripts/lib` to `mypy_path` **aborts mypy outright**:

```
scripts/lib/sentinel/model.py: error: Source file found twice under different module names:
  "sentinel.model" and "lib.sentinel.model"
Found 1 error in 1 file (errors prevented further checking)
```

`errors prevented further checking` means a config flip does not merely add findings — it stops
the gate from checking **anything**. That is strictly worse than the present blind spot, because
a gate that aborts still exits non-zero and looks like it ran.

## The options, none taken here

1. **Leave it, and rely on pyright** for this class. Cheapest and already true in practice, but it
   means the CI gate and the IDE disagree permanently, and CI is the one that blocks a publish.
2. **Normalise the imports** to one convention across the 29+ affected modules. Correct, but it
   touches every hook/detector entry path and the runtime `sys.path` assumptions with it.
3. **Per-module mypy overrides** that map the bare names. Narrow, but it encodes the duplication
   rather than removing it, and the `sentinel` collision has to be solved either way.

## Acceptance

- [x] A decision among 1/2/3, recorded with its reason — **option 1**, on the corrected grounds
      above (pyright already owns this class as a blocking CI gate). Not drifted into: the
      deciding fact is `ci.yml:46`, quoted.
- [x] `mypy scripts/ --ignore-missing-imports` still exits 0 — verified, 477 files clean. The
      `sentinel.model` double-resolution is NOT proven absent and does not need to be: it blocks
      only options 2/3, which were not taken. Stated rather than silently dropped.
- [x] The divergence is written down where a future session meets it — a "WHICH CHECKER OWNS
      WHAT" block sits in `pyproject.toml` immediately above `mypy_path`, naming the abort that
      punishes the obvious fix.

## Notes and lessons learned

## Approval log
