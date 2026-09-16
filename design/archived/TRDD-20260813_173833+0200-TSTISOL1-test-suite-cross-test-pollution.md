---
trdd-id: TSTISOL1
title: The test suite leaks state between tests — a test passes alone and fails in company, and writes into the real repo
column: complete
implementation-commits: [a749dfcc]
created: 2026-08-13T17:38:33+0200
updated: 2026-08-14T15:05:00+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-13T19:30

**RESOLVED in the working tree; NOT YET COMMITTED** (a stale `.git/index.lock` blocks the
index — `lsof` shows no process holds it). Nothing below is speculation; the mechanism was
proven before it was fixed.

- **CAUSE (proven, not the card's first hypothesis).** `state.state_dir` / `janitor_root` /
  `project_root` / `log_dir` are all `@lru_cache`d, so the FIRST call in a process pins the
  answer for the whole run. `del sys.modules["state"]` — the idiom ~22 test files isolate
  with — unbinds the NAME but cannot touch the OBJECT its importers already hold.
  `findings_ledger` does `import state` at module level, so after one delete+reimport it
  resolves through a module whose cache still points at the PREVIOUS test's tmp dir, or —
  when it bound before any fixture ran — at the REAL REPO. `set_project_dir_override`, the
  card's original suspect, is NOT involved.
- **PROOF.** A two-test pair, one variable: the same idiom WITHOUT the new conftest gave
  `test_second` a correct `state.state_dir()` but a `ledger_path(None)` pointing at
  `test_first0`, with `findings_ledger.state is state` False. WITH it, both agree.
- **FIX (at the source).** `tests/conftest.py::_clear_state_path_caches` — an autouse
  fixture that clears those resolvers on EVERY live copy of the module, before and after
  each test. Clearing beats deleting: it repairs every HOLDER at once where a delete
  repairs only the next importer, and nothing in `state` captures a path at import time
  (verified — no module-level env reads), so a reimport buys nothing a clear does not.
- **GUARD.** `tests/test_state_cache_isolation.py` — the pinned pair plus a check that the
  importer's module is among those cleared, so the guard cannot go quietly vacuous.
- **VERIFIED.** This card's own reproducer subset: 576 passed. Broader sweep: 1808 passed.
- **NEXT ACTION:** clear the stale lock, then commit `tests/conftest.py` +
  `tests/test_state_cache_isolation.py`; then decide the `[plugin-data] CHANGED` question
  below, which is the one acceptance box still genuinely open.
- **NOT FIXED, and NOT this card's fault:** `test_spawn_skips_failing_launcher`,
  `test_run_workload_retries_once_on_nonzero_exit`,
  `test_crash_loop_no_fallback_is_failopen_noop`. All three reproduce at pristine HEAD with
  every working-tree edit stashed, so they predate this work. They are themselves
  order/environment dependent — do NOT fold them into this card.

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

- [x] The minimal failing PAIR is identified and named (which test pollutes which) — any test
      that resolves a path first pollutes every later one THROUGH an importer holding the
      stale module; pinned as the pair in `tests/test_state_cache_isolation.py`
- [x] The mechanism is read out of the code, not inferred — the `@lru_cache` on `state`'s
      path resolvers, surviving `del sys.modules["state"]` via importer-held references
- [x] Fixed at the SOURCE (isolation), never by relaxing the assertion or reordering tests
- [x] A regression guard that FAILS if the leak returns — the pair, pinned, plus a check
      that the importer's module is actually among those cleared
- [x] A decision recorded on the `[plugin-data] CHANGED` writes: **ACCEPTABLE — the
      daemon's own writes, not test leaks.** See "The `[plugin-data] CHANGED` verdict" below
- [x] `uv run pytest -q` and the failing `-k` subset both green — the subset is 576 passed;
      the full suite's only failures are the three pre-existing ones named in the STATE
      block, which reproduce at pristine HEAD

## The `[plugin-data] CHANGED` verdict — acceptable, with one thing worth knowing

**Decision: ACCEPTABLE.** Those writes belong to the janitor's live global daemon, not to
the suite. Two independent reasons, either sufficient:

1. **The guard already proves it.** `conftest.daemon_ticked` credits a global-state
   mutation to the daemon only on PROOF — a live pid at both ends of the run AND an
   ADVANCED heartbeat. A stale pid file or a wedged process both fail it.
2. **A test physically cannot reach those paths.** Every observed path
   (`usage-probe/*.json`, `oauth-usage-cooldown.json`, `memory-guard.ps-snapshot.txt`,
   `keychain-denied.latch`) resolves under `$HOME`, and `pytest_configure` redirects `HOME`
   session-wide for every test. The daemon holds the REAL `HOME`; the suite does not.

**But the reasoning had a hole until this card was fixed.** `daemon_ticked`'s own docstring
justifies its relaxations with *"a leaking test writes project/plugin state, never … in the
REAL global-state dir (every test is isolated to a tmp dir)"*. That premise is precisely
what this card disproved: the `lru_cache` leak let a test resolve REAL repo paths. The
attribution is sound NOW because the cache-clear restores the isolation it assumed — it was
not sound before, and nothing in the guard would have said so.

**Latent gap, not worth fixing today but worth recording:** `usage_probe.probe_dir()`
documents `JANITOR_USAGE_PROBE_DIR` as the override "for tests", yet no test infrastructure
sets it — `_ISOLATION_ENVS` does not list it. It is harmless while `HOME` isolation holds,
but it is a documented second line of defence that is not actually wired, so it would not
catch the case it exists for.

## Notes and lessons learned

- **A guard's soundness argument can quietly depend on a premise another bug has already
  broken.** `daemon_ticked` was correct code resting on "every test is isolated to a tmp
  dir", which was false for months. Nothing failed: the guard kept passing, because the
  premise it relied on is not one it checks. When auditing a check, read what it ASSUMES,
  not only what it asserts.
- **A test fixture that does not reproduce production's data shape tests nothing.** The
  `check5` severity tests all passed while real cards were graded wrong, because the fixture
  was blank-line-separated prose and every real STATE block is a tight bullet list.

## Approval log
