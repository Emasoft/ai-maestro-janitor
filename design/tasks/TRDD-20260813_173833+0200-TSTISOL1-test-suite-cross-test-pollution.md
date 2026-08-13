---
trdd-id: TSTISOL1
title: The test suite leaks state between tests — a test passes alone and fails in company, and writes into the real repo
column: todo
created: 2026-08-13T17:38:33+0200
updated: 2026-08-13T17:38:33+0200
current-owner: unassigned
task-type: infra
approval-tier: 0
scope: project
severity: high
relevant-rules: []
npt: []
eht: []
---

# A test that passes alone and fails in company is a suite you cannot trust

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

**Found 2026-08-13 while verifying an unrelated change.** Opened at the USER's direction to
investigate and fix the test system, not just this one test.

### The reproducer, exact

```
uv run pytest tests/test_fleet_status_headless_flags.py -q          → 13 passed
uv run pytest -q                                                    → 15135 passed
uv run pytest tests/ -k "dispatch or iterm or session_liveness or fleet" -q
   → FAILED tests/test_fleet_status_headless_flags.py::test_no_override_still_lands_in_the_project_reports_dir
```

Reproducible, not flaky: the subset fails every run, isolation passes every run. Verified it is
NOT caused by the working-tree changes of the moment — `git stash` → pass, `git stash pop` → pass
in isolation, still fail in the subset.

### What actually happens

```
assert got.parent == tmp_path / "reports" / "fleet-status"
E  PosixPath('/Users/…/ai-maestro-janitor/reports/fleet-status')          ← the REAL repo
E  == (PosixPath('/private/var/folders/…/test_no_override_still_lands_i0') / 'reports' / …)
```

The test sets `monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))` on its FIRST line
(`tests/test_fleet_status_headless_flags.py:122`) and the code still resolved the REAL project
root. So under the subset, something either **outranks** that env var or **pre-empts** it.

**Two consequences, and the second is the worse one:**

1. The suite's result depends on WHICH tests run together. A green `-k` subset proves nothing,
   and a red one may accuse innocent code — this failure first appeared while reviewing an
   unrelated iTerm change and cost time before `git stash` cleared that suspicion.
2. **The test WROTE INTO THE REAL REPO** — `reports/fleet-status/janitor-global-status-…html`.
   Not a commit risk (`reports/` is gitignored — verified with `git check-ignore`), but a test
   that escapes its `tmp_path` at all can escape it somewhere that is not ignored.

## The investigation, not yet done — do NOT assume the cause

The obvious suspect is `state.set_project_dir_override`, whose docstring says it is used "only
when CLAUDE_PROJECT_DIR is unset" — if a sibling test leaves an override set AND the resolution
order actually prefers it, that explains everything. **That is a hypothesis, not a finding.**
Equally consistent: a module-level cache that captured the real root at import time (so the
env var is read once, before the monkeypatch), or a `functools.lru_cache` on a path resolver.

Settle it by bisecting the subset to the minimal failing PAIR, then reading the resolution
order in `state.project_root` — not by patching the assertion.

## Scope — the SUITE, not this test

This card is about the isolation contract, because one leak found by accident implies others
that have not been:

- Which module-level/global state survives a test? (`state` overrides, `lru_cache`s, the
  plugin-data dirs the runner already prints as `[plugin-data] CHANGED:` lines)
- Is there a fixture that should be `autouse` and is not?
- The runner ALREADY reports plugin-data mutation on nearly every run
  (`[plugin-data] CHANGED: …/usage-probe/*.json`, `…/global-state/*`). That is real state
  escaping into the user's machine-global janitor dirs during tests, and nobody treats it as a
  failure. Decide deliberately whether it is acceptable or a defect.

## Acceptance

- [ ] The minimal failing PAIR is identified and named (which test pollutes which)
- [ ] The mechanism is read out of the code, not inferred — resolution order, cache, or fixture
- [ ] Fixed at the SOURCE (isolation), never by relaxing the assertion or reordering tests
- [ ] A regression guard that FAILS if the leak returns — e.g. the pair, pinned, in one test
- [ ] A decision recorded on the `[plugin-data] CHANGED` writes: acceptable, or a defect to fix
- [ ] `uv run pytest -q` and the failing `-k` subset both green

## Notes and lessons learned

## Approval log
