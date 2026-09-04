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

## ☠ HYPOTHESIS 5, DEAD ON ARRIVAL — per-worker fd / process-table exhaustion

**RETRACTED ~20 minutes after I recorded it as "the leading hypothesis" in `1dce8845`.
Refuted by the very measurement it claimed to uniquely explain.**

**Why it is dead:** `subprocess.Popen.__init__` does not return until `_execute_child`
completes, and that path raises on every resource failure. fd exhaustion (EMFILE/ENFILE) hits
`os.pipe()` for the errpipe **before the fork** → `OSError` in the parent, no Popen object.
fork/proc-table failure (EAGAIN/ENOMEM) → raises. And a child that fails at `exec` writes the
exception down `errpipe_write` before `_exit`; the parent reads it and **re-raises it** — that
is why a missing binary surfaces as `FileNotFoundError` *from the `Popen(...)` call*. CPython
closed the silent-child path deliberately.
**The measured failure has `Popen` returning a LIVE object with a readable `returncode`, the
poll loop running to full exhaustion, and the failure landing at `read_text()`.** So the child
**was created and DID exec successfully.** Exhaustion-at-spawn predicts an exception at
`:274`/`:138`. That is not what happens.

**Two further errors in how I recorded it, both this card's own retracted patterns:**
- **`_SPAWNED_PIDS` was never evidence.** A `set` of ints exhausts nothing — not fds, not the
  process table, not memory. Its only qualification was that it is per-process state growing
  serially and fresh per xdist worker, which *matches the shape* of serial-fails/xdist-passes.
  I promoted a shape match to "one weak positive signal", which is the `E `-census error.
- **"Load average ⇒ fewer free fds/procs machine-wide" is not a mechanism.** Load average
  counts RUNNABLE PROCESSES. A box at load 15 is not measurably nearer `kern.maxproc` than at
  load 11. That row was the only one addressing the soak8/soak9 load evidence, and it was
  doing so with an assertion, not a cause.

**AND THE TWO-CARDS-ONE-BUG FRAMING IS WITHDRAWN — it is `c54627f0`'s retracted error one
level up.** Q8PNPRTW's `assert 'BRPROT-001' in ''` is a **detector subprocess exiting 0 with
empty stdout**, which has a DOCUMENTED, DESIGNED cause: `run_subprocess` fails open on timeout,
returns None, the caller's `if x is None: return 0` fires. `timeout_scale`'s own docstring
describes that exact scenario. **That is a TIMEOUT.** This card's zero-write measurement
*refutes* timeouts — a timeout predicts a LATE write, and no write ever landed. The two cannot
share a mechanism, and unifying them on "both look empty" is precisely "both raise
FileNotFoundError" at a higher abstraction, where it is harder to see rather than more
defensible. **Risk if left standing: scaling Q8PNPRTW's timeouts and declaring this card
solved.**

**MEASURED AFTERWARDS, and it independently kills the exhaustion story on this box:**
`ulimit -n` = **1,048,576**; `kern.maxfiles` = 491,520; `kern.maxfilesperproc` = 245,760.
There is no plausible regime where a pytest worker approaches those. Do not re-raise fd
exhaustion here without new numbers.

**ALSO MEASURED, and it is the load-sensitivity again:** row 2 run 6× solo with `-s` at host
load ~9 → **6/6 PASSED**, so no failing run's child stderr was captured (the point of the
run). Earlier today the same test failed **3/3 solo at load ~15**. Same test, same code, same
day; the only variable that moved is host load.

**What actually fits the data, and it is all that fits:** the child exec'd successfully, then
produced no filesystem effect, and it happens far more at high host load. Cause unknown.
Naming that "fd exhaustion" was a label, not a mechanism.

**THE MEASUREMENT STILL OWED — and note the trap:** capture a FAILING run's child stderr.
Row 1/row 2 inherit the parent's stderr (no `stderr=` at `:274`), so `-s` would show anything
`/bin/sh` printed. **But failures need a loaded box, and the box is quiet now.** Either run it
under a concurrent full-suite run, or accept that this measurement is only available when the
machine is busy. Six clean runs proved nothing except that the bug is load-gated.

*(Original text below, kept as provenance for a hypothesis that lived 20 minutes:)*
**This is the only candidate that explains BOTH this card and `TRDD-Q8PNPRTW`, and it is the
first one that predicts the ZERO-WRITE signature instead of merely tolerating it.**

A `fork()`/`Popen` that fails under fd or process-table pressure produces **no child at all**
— or one that dies instantly at `exec`. That is exactly what the marker measured: not a late
write, not a partial write, **no write**. Every timeout/latency story predicts a LATE write and
is therefore refuted by the marker data, which is why four of them died on Q8PNPRTW.

It also explains Q8PNPRTW's ten load-artifact failures, whose signature is
`assert 'BRPROT-001' in ''` — a detector exiting 0 with **empty stdout**, which is what a
failed spawn looks like to a caller that fails open. **Two cards, two "different" mechanisms,
one possible resource bug.**

Fits every observation on the table:

| observation | explained? |
|---|---|
| fails in the FULL suite (each xdist worker runs ~1,170 tests, accumulating) | ✅ |
| passes in an 88-test `-n auto` run (~6 tests/worker, nothing accumulates) | ✅ — **regardless of suite size or worker count**, so it survives the confounds that sank the fan-out story |
| passes serially in fresh per-invocation processes | ✅ |
| child produces ZERO filesystem effect, never a partial one | ✅ — uniquely |
| worse at higher host load (soak8 11.39 PASS vs soak9 15.53 FAIL) | ✅ — a loaded box has fewer free fds/procs machine-wide |

**Cheap tests, in order:** (1) do failures CLUSTER in the xdist workers that have run the most
tests? (2) sample `lsof -p <worker>` count, or `ulimit -n` headroom, at intervals during a full
suite run. (3) run the full suite at `-n 4` — fewer workers, each running MORE tests: the
fan-out story predicts improvement, exhaustion predicts it gets WORSE or stays. **That third
one is a genuine discriminating prediction and it is one run.**

**Not yet tested. Recorded as the leading hypothesis, not a finding** — four have already died
on Q8PNPRTW for being plausible.

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
