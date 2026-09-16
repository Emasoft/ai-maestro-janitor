---
trdd-id: TY2EZ8ZH
title: Throttle the daemon marketplace-refresh subprocess to low CPU+IO priority
column: published
created: 2026-06-25T22:16:12+0200
updated: 2026-06-25T22:46:43+0200
published-version: 0.24.16
published-at: 2026-06-25T22:46:43+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 2
severity: MEDIUM
effort: S
labels: [daemon, throttle, marketplace-refresh, performance]
task-type: infra
parent-trdd: null
npt: []
eht: []
blocked-by: []
supersedes: []
superseded-by: []
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
must-pass-tests-before-merge: true
test-requirements: [unit, lint, typecheck]
audit-requirements: []
review-requirements: []
runtime-targets: [macos, linux]
impacts: []
attempts: 0
test-failures: 0
last-test-result: pass
implementation-commits: [ca0198e]
external-refs: ["task #244"]
---

# TRDD-TY2EZ8ZH — Throttle the daemon marketplace-refresh subprocess to low CPU+IO priority

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-06-25

**Current state:** DONE (implemented + verified). TRDD committed `22fc199`;
code+tests committed in this session's implementation commit.

- `scripts/lib/daemon_throttle.py` — NEW module. Holds the PURE
  `low_priority_prefix(platform, *, has_taskpolicy, has_nice, has_ionice)` and the
  thin detector `_low_priority_prefix()` + `nice_preexec()` (POSIX `os.nice(19)`
  baseline, fail-open).
- `scripts/daemon.py` — `task_marketplace_refresh` prepends the prefix to the
  `claude plugin marketplace update` argv and passes the nice preexec; ANY error
  falls through to the CURRENT un-throttled invocation. `_run_workload` /
  `_run_workload_once` gained an OPTIONAL `preexec_fn=None` param (behavior
  unchanged for every other caller).
- `tests/test_daemon_throttle.py` — NEW. 25 tests: parametrized pure-function
  matrix + detector seam + `nice_preexec` + 3 wiring tests (prefix applied when
  tools present, bare fallback when absent, fail-open on build error).

**VERIFIED:** `uv run pytest tests/test_daemon_throttle.py -q` → 25 passed.
Regression: `test_daemon.py` + 3 marketplace tests → 54 passed. `uv run ruff
check` + `uv run pyright` on the 3 changed files → clean (0 errors).

**NEXT ACTION:** none — task complete. (Future ship: this rides to `published`
via the normal publish pipeline; not part of this task.)

**Load-bearing facts / gotchas:**
- FAIL-OPEN is NON-NEGOTIABLE: the daemon is a machine-wide singleton. A throttle
  bug must NEVER break marketplace-refresh or the daemon. Every prefix-build and
  preexec path is wrapped so it degrades to the existing un-throttled call.
- SCOPE: only the marketplace-refresh subprocess. Do NOT touch the other daemon
  tasks, the marketplace_lock, or `run_subprocess`'s behavior for other callers.
- `state.py` is imported EVERYWHERE; do NOT add `shutil`/`platform` imports there.
  The new concern lives in its own module imported only by `daemon.py`.
- `taskpolicy -b` (macOS) puts the process in the background QoS band → throttles
  CPU + IO + network as a unit; on Linux use `nice -n 19` + `ionice -c 3`.
- The PURE function takes `platform` + bools directly → no mocking needed in tests.

**SUPERSEDED — do NOT carry forward:** (none yet)

**Durable artifacts to read before acting:**
- `reports/daemon-throttle/<ts>-task-244.md` (final report, written at completion).

## Problem

The global janitor daemon's `task_marketplace_refresh` (`scripts/daemon.py`) runs
`claude plugin marketplace update` every ~20 min (default
`_INTERVAL_MARKETPLACE_REFRESH = 1200`). That command is a CPU+IO-heavy re-clone /
refresh of every configured marketplace. Observed repeatedly this session: while it
runs it **starves the user's foreground work** — Bash commands time out, agents
crawl, CI-transit operations time out. (Concretely: a trivial `gen() { ... }; ls ...`
shell loop timed out after 8+ minutes during this very task, which is exactly the
starvation symptom.)

The subprocess is spawned by `_run_workload` → `_run_workload_once`, which uses
`subprocess.Popen([...], ...)` with no priority hint, so it competes with the
foreground at normal scheduler + IO priority.

## Fix — run the marketplace-refresh subprocess at LOW CPU+IO priority

Cross-platform, minimal, reusable, FAIL-OPEN. Two layers:

1. **A command-prefix** that wraps the argv with the OS's low-priority launcher:
   - macOS (`darwin`) + `taskpolicy` present → `['taskpolicy', '-b']` (background
     QoS band — throttles CPU, IO, AND network together, yielding to foreground).
   - Linux → `['nice', '-n', '19']` (if `nice` present) + `['ionice', '-c', '3']`
     (if `ionice` present — idle IO class).
   - Anything unavailable → that part is dropped; nothing available → `[]`
     (FAIL-OPEN: run un-throttled, exactly as today).
2. **A POSIX `preexec_fn`** doing `os.nice(19)` as a CPU baseline even when no
   external launcher exists (e.g. macOS without `taskpolicy`, or a stripped Linux).
   Wrapped in try/except and skipped where `os.nice` is unavailable (Windows).

### Pure function (fully unit-testable, no I/O, no mocks)

```
low_priority_prefix(platform: str, *, has_taskpolicy: bool,
                    has_nice: bool, has_ionice: bool) -> list[str]
```

- `platform == 'darwin'` AND `has_taskpolicy` → `['taskpolicy', '-b']`
- `platform.startswith('linux')` → `['nice','-n','19']` (if `has_nice`)
  plus `['ionice','-c','3']` (if `has_ionice`)
- otherwise / nothing available → `[]`

### Thin caller (detects, then calls the pure function)

```
_low_priority_prefix() -> list[str]
```
Reads `sys.platform` + `shutil.which(...)`; FAIL-OPEN to `[]` on any exception.

### Wiring

`task_marketplace_refresh` builds `prefix + ['claude','plugin','marketplace','update']`
and calls `_run_workload(argv, preexec_fn=nice_preexec())`. The prefix-build and the
preexec are each wrapped so ANY failure falls back to the current un-throttled
`['claude','plugin','marketplace','update']` with `preexec_fn=None`.

`_run_workload` / `_run_workload_once` gain an OPTIONAL keyword `preexec_fn=None`
threaded into `subprocess.Popen`. Default `None` ⇒ byte-identical behavior for
every existing caller (user-plugins-update, version-update, oauth-tick, …).

## Test plan (TDD, real, no mocks of the code under test)

1. Parametrized tests of `low_priority_prefix` over
   (`darwin`/`linux`/`linux2`/`win32`/`other`) × (each tool present/absent),
   asserting the EXACT prefix list incl. the fail-open `[]` cases. Pure function ⇒
   pass platform + bools directly.
2. A wiring test: with the tools "present" the built argv carries the prefix; with
   them "absent" the argv is the bare command (clean fallback). Exercised by
   monkeypatching `sys.platform` + `shutil.which` for `_low_priority_prefix()` only
   (the detection seam), NOT the pure function.
3. `nice_preexec()` returns a callable on POSIX (and calling it never raises) and
   `None` where `os.nice` is unavailable; the callable swallows any `os.nice`
   error (fail-open).
4. `uv run pytest tests/test_daemon_throttle.py -q` — pass.
5. `uv run ruff check` + `uv run pyright` on changed files — clean.

## FAIL-OPEN contract (non-negotiable)

The daemon is the machine-wide singleton; a throttle defect must never break
marketplace-refresh or wedge the daemon. Therefore:
- The prefix is computed defensively; any exception ⇒ `[]`.
- The preexec is computed defensively; any exception ⇒ `None`.
- The wiring wraps both so the worst case is the **current** un-throttled
  invocation — never a crash, never a skipped refresh.
- Scope is the marketplace-refresh subprocess ONLY.
