---
trdd-id: PAHO6KWK
title: The rotator wedge tick sets its env flag in the whole daemon process so other threads' subprocesses inherit it
column: testing
status: tasked
created: 2026-10-06T17:25:57+0200
updated: 2026-10-18T03:49:38+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T17:25:57+0200
implementation-commits: [bdf9d50a]
---

# The rotator wedge tick sets its env flag in the whole daemon process so other threads' subprocesses inherit it

scripts/daemon.py ~3422-3426: the tick thread sets os.environ["JANITOR_ROTATOR_WEDGE_TICK"]="1" around task.run() and pops it in a finally. os.environ is process-global: while a wedge tick runs, every subprocess started with the inherited environment by any other daemon thread inherits (which threads shell out while a wedge tick runs, e.g. the process-size watch, is INFERRED, not read) JANITOR_ROTATOR_WEDGE_TICK=1, and mutating the environment while another thread forks is not thread-safe. Fix: pass the flag only in the rotator subprocess env (env={**os.environ, "JANITOR_ROTATOR_WEDGE_TICK": "1"}) instead of mutating os.environ; a test that fails before (another thread's subprocess sees the flag) and passes after. Found by the review of a4426a8e (the test race fix), 2026-10-06.

## Approval log

- 2026-10-06T17:25:57+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T21:59:19+0200 — column → testing by main-agent@ai-maestro-janitor. built and gated; field proof waits on a release

## Findings

2026-10-10 21:42 BUILT: wedge flag moved off os.environ: _RotatorTickThread marks _thread_state.wedge_tick around task.run(), task_oauth_rotator_tick passes env={JANITOR_ROTATOR_WEDGE_TICK:1} via new env kwarg on _run_workload/_run_workload_once (merged over inherited env, reaches every retry attempt); only caller of the tick is the own_thread beat on the tick thread, so thread-local is safe. Red before on HEAD: 4 failed (leak test, env-handed test, mark-cleared test, retry-env test); after: 117 passed across the 6 files using _run_workload, ruff/mypy/pyright clean. Not covered: JANITOR_ROTATOR_HEADLESS is still written into os.environ by the same function so {**os.environ} copies it and the rotator subprocess behaviour for that flag is unchanged (same process-global shape, out of scope); which other threads shell out during a tick was not listed.
2026-10-10 21:59 GATE on the built tree: 18364 passed, 2 skipped; ruff, mypy, pyright exit 0 (reports/board/gate-paho6kwk.txt). The main session read the callers itself: one production caller of the tick (daemon.py line 851, the own-thread beat), the main loop skips own-thread tasks (line 3252), and the task's run calls its function on the calling thread. Two edits by the main session: an unrelated comment the worker had shortened (TRDD-5EHBPH6G) was restored before the gate; after the gate the separate Mapping import was folded into the existing typing import (re-checked: ruff, mypy, pyright, the two rotator test files). Takes effect in the daemon only after a release.

## Acceptance

- [x] os.environ never carries the wedge flag during a wedge tick, seen from the task and from another thread's real subprocess (test red before the fix).
- [x] The rotator subprocess still receives the flag on a wedge tick, on every retry, and not on a beat tick.
- [ ] FIELD, after a release: a wedge-triggered rotation still debounces the live 429 (daemon log of a wedge tick).
