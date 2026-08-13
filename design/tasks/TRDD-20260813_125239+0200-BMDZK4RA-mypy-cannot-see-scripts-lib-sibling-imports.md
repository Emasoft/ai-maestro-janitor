---
trdd-id: BMDZK4RA
title: The mypy gate cannot see cross-module calls between scripts/lib siblings
column: todo
created: 2026-08-13T12:52:39+0200
updated: 2026-08-13T12:52:39+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

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

- [ ] A decision among 1/2/3, recorded with its reason — not drifted into
- [ ] Whatever is chosen, `mypy scripts/ --ignore-missing-imports` still exits 0 AND the
      `sentinel.model` double-resolution is proven absent (it is the blocker for options 2/3)
- [ ] If option 1: the divergence is written down where a future session meets it, so the next
      person to see a pyright-only error does not re-derive this card from scratch

## Notes and lessons learned

## Approval log
