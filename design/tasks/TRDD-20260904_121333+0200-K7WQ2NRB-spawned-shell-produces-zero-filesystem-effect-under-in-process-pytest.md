---
trdd-id: K7WQ2NRB
title: a spawned shell produces zero filesystem effect under in-process pytest — capture_all_logins rows 1 and 2
column: todo
created: 2026-09-04T12:13:33+0200
updated: 2026-09-04T12:13:33+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
severity: medium
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [tests, flaky, suite-health, publish-blocker]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
external-refs: [TRDD-Q8PNPRTW]
---

# A spawned shell produces zero filesystem effect under in-process pytest

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-04

- **WHY THIS CARD EXISTS.** Split out of `TRDD-Q8PNPRTW` (rule 13, one atomic task per TRDD).
  That card is `blocked` on a USER waiver for a bucket of load artifacts. **These two failures
  are blocked on nobody** — they are live technical work, and parking them behind a human
  decision that has nothing to do with them would hide them. They shared Q8PNPRTW only because
  they surfaced in the same soak run: provenance, not atomicity.
- **THE TWO TESTS** (`tests/test_capture_all_logins.py`):
  - `test_kill_process_group_terminates_a_grandchild_too` (row 1) — spawns its own `Popen`,
    inherited env, 50 s poll budget.
  - `test_capture_one_kills_the_whole_tree_and_reports_timeout` (row 2) — goes through
    `cal.capture_one(..., env={}, timeout=1.0)`, `cwd=str(_ROT)`, 10 s + 30 s poll.
  **Do NOT assume they share a cause.** Q8PNPRTW retracted that assumption twice
  (`c54627f0`, `db466c64`): the identical `FileNotFoundError` shape discriminates nothing.

## What is MEASURED

- **When they fail, the child produces ZERO filesystem effect.** A temporary marker line
  (`echo started > {pid_file}.started`) as the script's FIRST statement, run 8×, then reverted:
  **3/3 failing runs wrote NEITHER file; 6/6 passing runs wrote BOTH.** Marker and pid file
  **never disagree** — there is no run with `.started` but no pid — which is what rules out
  partial execution (child ran, forked, died before the second redirect).
- **Budgets are ample and are NOT the cause.** `slack = 10.0`, so row 1 polls 50 s and row 2
  polls 30 s after a 10 s `communicate`; the loops run to full exhaustion (`_` = 499 / 299).
  `capture_one`'s `timeout=1.0` really does become 10 s — `tests/conftest.py:812-884` wraps
  `Popen.communicate`/`wait` to scale an explicit numeric `timeout=`, and there is **no**
  `no_timeout_scale` marker in the file (grepped).
- **Fork latency is not the cause.** 50 standalone trials at load 14.8–21.2: median
  0.027–0.086 s, max **2.74 s once**, 0 timeouts. A 10 s / 50 s budget does not lose to that.
- **Rates:** row 2 fails 3/3 solo and in all 3 paired runs (`/tmp/pair_2.txt`, `pair_3.txt`
  name it in their `FAILED` lines). Row 1 is intermittent — 1/3 solo in one batch, 0/4 in a
  later one. Both pass more often under `-n auto` than serially.

## Excluded BY READING SOURCE (not by inference)

| candidate | why it is out |
|---|---|
| `PATH` / `env={}` starving `sleep` | `$!` is assigned at **fork**; the redirect is the shell's own, so the pid write needs neither `PATH` nor a successful `exec` of `sleep`. Script read first-hand at `:265-270` / `:311-316`. |
| load starvation past the budget | budgets are 10 s / 50 s; measured worst fork+write is 2.74 s |
| sandbox guard DENIED the spawn | a denial raises inside the patched `Popen.__init__`, so the test would fail AT the spawn; it fails at the later `read_text()` |
| `is_tmp_path` / `/var` vs `/private/var` mismatch | `sandbox_guard.py:263` lists BOTH forms and realpaths them |
| guard rewriting the spawn | `sandbox_guard.py:727` calls `original_init(self, args, *a, **kw)` unmodified |
| guard hardening the child env | `_harden_child_env` returns `child_env` UNCHANGED for a non-Python spawn (`:350-351`) |
| `capture_one` cleanup deleting the pid file | its single `unlink` (`capture_all_logins.py:163`) targets `_bootstrap_pid_path(email)`, a different path, and only when the content matches its own pid |
| parent signal disposition | `start_new_session=True` calls `setsid()`; `exec` resets handled signals; only `SIGCHLD=SIG_IGN` survives and that would break `wait` (line 4), not the line-2 write |
| cross-test state **within a process** | row 2 fails 3/3 **solo**, in three separate processes. **This does NOT exclude state that persists OUTSIDE the process across consecutive runs** — a stale lock file, a leaked `sleep 600` from a prior run, an OS-level resource. The solo runs were sequential in one shell, so cross-RUN state is untested. |

## What the marker CANNOT tell us

The evidence shows no write landed. It does **not** distinguish: (a) `exec` never happened,
(b) `exec` happened and the child died before completing the write, (c) `exec` happened and
writes into that directory failed. Q8PNPRTW published "the shell never runs" and had to
retract it — **do not repeat that.**

## NEXT ACTION

1. **Read `_enforce_spawn`** (`tests/sandbox_guard.py:726`, called before `original_init`). It
   is the only function in the spawn path nobody has opened. **This is the cheapest next read,
   NOT a lead** — it is suspicious by elimination, which is the reasoning that produced three
   dead diagnoses on Q8PNPRTW. One weak positive signal: `:730` grows an unbounded
   module-level `_SPAWNED_PIDS` set that persists across a serial session but is fresh per
   xdist worker — an asymmetry matching serial-fails / xdist-passes.
2. If that is clean, instrument to separate (a)/(b)/(c) — e.g. capture the child's exit status
   and stderr directly rather than inferring from the pid file's absence.

## Acceptance criteria

- [ ] The mechanism is NAMED and demonstrated — not "passes serially", not a widened timeout.
- [ ] Row 1 and row 2 each get their own verdict. They may share a cause; that must be shown,
      not assumed.
- [ ] Whatever fix lands, both tests pass 10/10 serially AND under `-n auto`.
- [ ] `uv run ruff check scripts tests`, `uv run mypy scripts/ --ignore-missing-imports` and
      `uvx --with pyright pyright` all clean.

## Notes

- Any probe that edits `tests/test_capture_all_logins.py` MUST be reverted with the Edit tool
  and verified by an empty `git status --porcelain` + `git diff`. The git guard refuses
  `git checkout --` here, correctly.
- Evidence: `reports/suite-failures/20260904_114209+0200-capture-all-logins-failure-state.md`,
  `reports/suite-failures/20260904_113039+0200-fixture-fork-latency.md`.
