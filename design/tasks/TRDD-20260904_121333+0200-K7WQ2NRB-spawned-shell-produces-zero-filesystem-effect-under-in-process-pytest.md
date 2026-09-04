---
trdd-id: K7WQ2NRB
title: a spawned shell produces zero filesystem effect under in-process pytest — capture_all_logins rows 1 and 2
column: todo
created: 2026-09-04T12:13:33+0200
updated: 2026-09-05T01:31:36+0200
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
- **2026-09-05, WEAK and in-config:** both rows passed in two consecutive full-suite runs
  (16416 passed, 11m03s / 13m02s), incidental to TRDD-2640RYR5. Host load unsampled, so
  unplaceable on the load axis; the module runs 0 skips standalone, so the suite's 1 skip is
  not these. Takes the full-suite cell from 2 points to 4 (soak8 PASS 11.39, soak9 FAIL 15.53);
  cannot narrow the cause — only a captured failure can.

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
**⚠ SCOPE, added 2026-09-04 18:44 — "a readable `returncode`" is MEASURED for ROW 1 ONLY.**
Row 1 binds its own `Popen` (`tests/test_capture_all_logins.py:274`), so the test can and does
observe it. **Row 2 never binds one** — `capture_one` owns the object internally and the test
sees only the `TimeoutExpired` it raises. For row 2 the equivalent is a WEAKER INFERENCE than
it first looks: reaching `:158` means the first `communicate(timeout=1.0)` timed out, and
`communicate` waits for **EOF on the pipes, not for the child to exit**. The backgrounded
grandchild inherits fds 1 and 2, so the write ends stay open after the direct child dies. A
`TimeoutExpired` at 1.0 s is therefore fully consistent with a child that exec'd, forked, and
exited immediately. It establishes **"some process still held the pipe write ends"**, NOT
"the child was alive" — the same fd-holding mechanism named in the drain hazard below, applied
one step earlier. *It is not nothing, either:* the only candidate for holding those fds is a
process the child forked, so it weakly implies the child got far enough to fork. Do not
over-correct this into "it tells us nothing". This block
predates the row-1/row-2 split and argued about `:274`/`:138` together; anything that leans on
it (including NEXT ACTION step 2) inherits this distinction.

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
*refutes* timeouts — a timeout predicts a LATE write, and no write ever landed. **Precisely:
the two cannot share THE TIMEOUT MECHANISM, and no relation between them is established.**
(Stating it as "cannot be related" — which I did — overreaches: a common upstream cause
manifesting as a timeout on one path and a dead child on the other is excluded by nothing I
measured, and both are load-gated and both spawn subprocesses.) Unifying them on "both look
empty" is still precisely "both raise
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

**What actually fits the data:** the child exec'd successfully, then produced no filesystem
effect, and it happens far more at high host load. Cause unknown for the FAMILY — but
**⚠ I over-retracted, and one live sub-hypothesis went out with the dead one:**

> **SURVIVING, UNTESTED: the child exec'd, then its own `open()` for the redirect failed.**
> The errpipe argument only reaches the SPAWN. Once `sh` is running the parent's `Popen` has
> already returned, and **nothing the child does afterwards can retroactively raise in the
> parent.** So: `sh` execs (parent sees success), `> {pid_file}` fails, `sh` exits non-zero, no
> file. That is live Popen + readable returncode + poll to exhaustion + zero write — **every
> measured fact**, with no parent exception required.
> Weaker than spawn-time exhaustion but NOT dead: ~1M fd headroom makes an *fd-specific*
> failure implausible, yet a redirect can fail for non-fd reasons (tmpdir gone, ENOSPC, a
> permissions/mtime race). **Its test is the stderr capture already owed above** — `sh` would
> print `cannot create ...` to inherited stderr *(**for ROW 2 that premise is false: the stderr
> is PIPEd, not inherited — see the correction above and NEXT ACTION step 1b**)*. I reasoned "the `-s` runs showed nothing"
> while my own card records that **all six of those runs PASSED**, so a failing run's stderr
> has still never been seen. I wrote that trap down and then walked into it one section later.

Naming the family "fd exhaustion" was a label, not a mechanism — but "cause unknown" must not
swallow the sub-hypothesis above, or a future session re-derives it from scratch.

**THE MEASUREMENT STILL OWED — and note the trap:** capture a FAILING run's child stderr.
~~Row 1/row 2 inherit the parent's stderr (no `stderr=` at `:274`), so `-s` would show anything
`/bin/sh` printed.~~ **FALSE FOR ROW 2 — corrected 2026-09-04 18:31, verified in source.**
Row 1 does inherit (`tests/test_capture_all_logins.py:274` — `subprocess.Popen([str(script)],
start_new_session=True, text=True)`, no `stdout=`/`stderr=`). **Row 2 does NOT:** it goes
through `cal.capture_one`, which spawns at `scripts/capture_all_logins.py:138` with
`stdout=subprocess.PIPE, stderr=subprocess.PIPE` (`:143-144`). Its child's stderr therefore
reaches a PIPE, is drained by `communicate()`, and is handed to
`subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr)` (`:158`) — which the
test discards, since `pytest.raises` binds no name and nothing inspects `.stderr`. **`-s`
cannot ever show row 2's child stderr, at any load.** The `:274` citation was row 1's line
number applied to both rows.
~~**But failures need a loaded box, and the box is quiet now.**~~ **Load alone is not
SUFFICIENT — see NEXT ACTION step 1a.** Six clean runs at load ~9, then 14 more at load
19.5–36.3, all passed. That is *not* a finding that load is irrelevant: all 20 ran in a
2-test selection, never inside the full suite where soak9 failed.

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

## NEXT ACTION — REORDERED 13:00; the old order is stale

0. **THE EXPERIMENT STEP 1a's SHAPE CANNOT PRODUCE — a full-suite loop with load sampling.**
   Step 1a burned 14 runs on a 2-TEST SELECTION and proved only that that configuration does
   not fail at load ≤36. The failing observations (soak9) are IN-CONFIG, i.e. the rows running
   inside the full-suite pytest process. So the experiment is: loop the FULL suite, sample host
   load throughout each run, and preserve every run's output — then a failure is caught in the
   configuration that actually fails, with its load on the record. Expensive by construction
   (~12 min/iteration), which is exactly why the 4 in-config data points so far are worth
   counting before spending more. Note this does NOT contradict step 1's "do not re-attempt by
   re-running the tests": that forbids re-running the 2-test selection, which is the shape that
   cannot reproduce.

1. **⇒ CAPTURE A FAILING RUN'S CHILD STDERR — NOT PERFORMED. The step splits by row: for
   ROW 1 it was ANSWERED FROM THE ARCHIVE (1c); for ROW 2 it is UNREACHABLE as written (1b).
   Rewrite this step before re-running it — and DO NOT re-attempt it by re-running the tests:
   14 attempts at load 19.5–36.3 produced no failure to capture (1a).**
   *No run in this session captured a failing child's stderr.* 18:12-18:24 was 14 failed
   reproduction attempts (1a); 18:38-18:55 was probe work establishing the inference rule.
   Row 1's answer came from reading an artifact produced hours earlier — an absence found in
   pre-existing evidence, which is the step being **superseded**, not the step working.

   **(1a) MEASURED — in a 2-TEST SELECTION, host load up to 36 does not reproduce.** 14 runs of both rows (`-s`,
   `-p no:randomly`, as a 2-test selection) against a concurrent full-suite load generator:
   **14/14 PASSED** at 1-min host loads **19.5 → 36.3**, sustained. Evidence:
   `reports/suite-failures/20260904_181243+0200-child-stderr-under-load/` (machine-local,
   gitignored — the numbers here are the record).
   **⚠ Scope is the whole claim. This licenses NOTHING about the full-suite configuration.** My first wording was
   *"a busy box is not the discriminator"*, and that is the config-confounded claim this card
   keeps catching: soak9 failed in the **full suite** at 15.53; these 14 passed in a **2-test
   selection** at 19.5–36.3. Two variables changed, one was blamed. A pass under high load in
   configuration B says nothing about whether load matters in configuration A. (The 2-point
   baseline was never a load curve either — soak8 PASSED at 11.39.) What was NOT reproduced is
   the shape this card is named for: the rows running *inside* the full-suite pytest process.

   **(1b) SOURCE FINDING (a code read, not a measurement) — this step was UNRUNNABLE FOR ROW 2
   as written.** **`-s` changes the PARENT's own fd 1/2 (which an inherited-fd child therefore
   also gets); it cannot reach a child whose fd 2 was explicitly replaced by a `PIPE`.**
   `capture_one` PIPEs both streams (`scripts/capture_all_logins.py:143-144`), so row 2's child
   writes fd 2 into a pipe that `communicate()` drains into `TimeoutExpired.stderr` (`:158`),
   which the test discards. So a failing row-2 run under `-s` would have shown nothing.
   *Do NOT read this as "`-s` affects nothing about children."* Under the default
   `--capture=fd`, pytest replaces the PARENT's fd 1/2 with temp files, so an inherited-fd
   child writes into pytest's capture and is reported as `Captured stderr call` on failure.
   **Row 1 was therefore reachable even WITHOUT `-s`** (`tests/test_capture_all_logins.py:274`,
   no `stdout=`/`stderr=`) — the earlier "only row 1 was reachable this way" understated it.

   **(1c) MEASURED on ONE archived run, and it costs the leading sub-hypothesis: THAT FAILING
   ROW-1 RUN'S CHILD PRINTED NOTHING TO STDERR.**
   The artifact is `reports/suite-failures/raw-captures-20260904/solo_r1_1.txt`, read in full
   (58 lines): **serial** (no `bringing up nodes` banner), row 1 alone, `F [100%]`, a fully
   rendered `FAILURES` block ending `1 failed in 60.09s`. It contains **no `Captured stderr
   call` section**, and no `sh:` text anywhere.
   **The inference rule is itself measured, AND transported into this repo's harness** —
   which matters, because a rule measured in a stock harness proves nothing about one whose
   whole job is wrapping `Popen` and file writes:
   | probe | harness | `Captured stderr call` | child's fd-2 marker inside it |
   |---|---|---|---|
   | `/tmp/test_capfd_child.py`, serial | stock, no conftest | present | **present** |
   | `/tmp/test_capfd_child.py`, `-n 2` | stock, no conftest | present | **present** |
   | `tests/test_zz_capfd_transport_probe.py`, serial | **repo conftest + `sandbox_guard` active**; row 1's spawn SIGNATURE (tmp_path script, no `env=`, no `stdout=`/`stderr=`, `start_new_session=True`) — *but its child echoes and exits, where row 1's is killed while `wait`ing* | **present** | **present** |
   | `tests/test_zz_lifecycle_probe.py`, serial | same harness, row 1's spawn **+ kill** sequence **on the PASSING path**: child echoes to stderr, backgrounds `sleep 600`, writes the pid file, `wait`s, then `cal._kill_process_group(proc)` kills it, then a forced assertion | **present** (line 28) | **present** (line 29) |
   The fourth row exists because the third row matched only the spawn signature, and the
   objection it had to answer was "does a SIGKILL mid-`wait` lose the child's earlier write?"
   **It licenses exactly that and no more: a child's fd-2 write is still reported after
   `_kill_process_group` kills it.**
   **⚠ It did NOT enter row 1's failing path**, and calling it a "full lifecycle" match (my
   first wording) was the THIRD narrowing of the same overstatement — *exact shape* →
   *signature* → *full lifecycle*, each a notch tighter and each still too broad. The
   disproof is in the timing: this probe is `1 failed in 3.29s`, so the pid file appeared and
   the poll loop broke on its first iteration; the archived failure is `1 failed in 60.09s`,
   the loop exhausting because the pid file never appears. **This is row 1's PASSING path with
   an assertion bolted on.** The case (1c) needs — a child that writes a diagnostic and does
   nothing else — is by construction not the healthy one exercised here.
   (Both in-repo probes were reverted to `.trashcan/20260904_183709+0200/` and
   `.trashcan/20260904_183937+0200/`; `git status --porcelain` verified clean after each.)
   **⚠ A trap for anyone repeating this: the lifecycle probe's FIRST attempt exited 2 at
   COLLECTION** (`ModuleNotFoundError: No module named 'capture_all_logins'` — it needs the
   `sys.path.insert(0, str(_REPO / "scripts"))` that `tests/test_capture_all_logins.py:15-18`
   does). An exit-2 run produces no test output at all, so **"no `Captured` section" and "the
   run never reached the test" are indistinguishable to a grep.** Check the exit code, not
   just the grep. (The import path itself is harmless to the result: `conftest.py` installs
   `sandbox_guard`'s wrappers process-wide at session start, so the same guards are active
   regardless of how the test module imports `cal`.)
   So `--capture=fd` captures a CHILD's inherited fd-2 writes and labels them
   `Captured stderr call` **inside this harness, across row 1's whole lifecycle**, and pytest
   omits the section entirely when nothing was captured.
   *(The stock probes show `grep -c Captured` = 2 vs the in-repo probes' 1. That is a grep
   artifact, not a harness difference: the stock probes' FUNCTION docstring contains the words
   "Captured stderr call" and pytest echoes it into the traceback. Every probe has exactly one
   real `----- Captured stderr call -----` section.)*
   **The argument that actually closes it needs no enumeration of channels.** My first version
   claimed the text must appear either inline (under `-s`) or in a `Captured` block — a
   dichotomy the file itself refutes: `solo_r1_1.txt` line 2 carries write-guard text sitting
   *inline, above* `=== FAILURES ===`, with no `Captured` section anywhere, so a third channel
   plainly exists (session/teardown output, printed outside per-test capture). Rather than
   enumerate channels in a harness that has an unusual write path (`sandbox_guard`'s
   `_REAL_OS_WRITE`), rest on the one mechanism this actually needs: **stderr is UNBUFFERED**,
   so the byte hits fd 2 at write time, not at exit. That fd was inherited from pytest, and the
   ENTIRE run was redirected into this 58-line file — so it would have landed there the instant
   it was written, regardless of channel or of what happened to the writer afterwards.
   *(An earlier version of this sentence added "and BEFORE it forks anything". **That is false
   for this script:** the failing redirect is on `echo $! > {pid_file}`, which runs AFTER
   `sleep 600 &` has already forked. The clause was doing no work — the forked `sleep`
   inherits the same fd 2 — so it is cut rather than repaired.)*
   **⚠ AND THE PREDICTED STRING IS WRONG. Measured 2026-09-04 19:14** on this machine's
   `/bin/sh` with the identical script shape (`sleep 600 &` then a redirect into a
   non-existent dir):
   ```
   /tmp/probe_sh.sh: line 3: /nonexistent_dir_xyz/grandchild.pid: No such file or directory
   ```
   The format is `<script>: line N: <path>: <reason>` — **not** `sh: cannot create …`, which is
   the string this card and Q8PNPRTW have been naming throughout. A future session grepping for
   `cannot create` would find nothing **even on a run that emitted the diagnostic.**
   *The `solo_r1_1.txt` conclusion survives*: that search was
   `grep -rniE "cannot create|Captured stderr|sh: |Permission denied|No such file"`, and the
   real format matches both `sh: ` (via `…grandchild.sh: line 3`) and `No such file`. Only the
   Python-level `FileNotFoundError` lines matched. **Grep for `: line ` next time, not for
   `cannot create`.**
   *(58 lines for a 60.09 s run is not an anomaly: the run polled silently for a minute, then
   printed one traceback. Duration and output volume are unrelated here.)*
   *Still unexcluded by the probes, though not by the redirect argument:* a write that happens
   after the test's call phase would be attributed to a different phase (or to no section at
   all); neither in-repo probe tests that, because in both the child's write precedes
   everything else.
   ⇒ On that run the child produced **no filesystem effect and no output at all** — while
   lines 88-94 argue a failed `execve` would have raised in the parent instead. That tension is
   now the sharpest thing on this card.
   **⚠ Why this is stated for ONE run and not for the archive.** My first version cited
   `grep -rn "Captured"` returning zero across *all* 36 captures. That inference rule is
   broken, and my own probe disproves it: a **passing** test never prints its captured
   sections, so a zero-hit grep over a directory of mostly-passing runs is compatible with
   children that printed plenty. Absence-of-a-section is only absence-of-output for a run that
   FAILED with its report rendered — which is why `solo_r1_1.txt` had to be read in full
   rather than grepped for.
   *Not yet excluded, and this is the ONLY reason left:* **n=1.** One failing run was found in
   the archive and read; nothing says the next failure behaves the same. Do not retire the
   sub-hypothesis on a single observation — but it now has a counter-observation it did not
   have before, and the inference rule behind it is measured in the harness that produced it.
   *(An earlier draft justified this caveat with "row 1 has passed 14/14 since". That is a
   non-sequitur — passing runs say nothing about what a FAILING run's child emits — and it
   made a sound caveat look like timidity.)*
   *Scope, precisely:* this closes **fd-2 writes by `/bin/sh`** — the case the surviving
   sub-hypothesis predicts (`sh: cannot create …`). It says nothing about an **exec failure**,
   which prints to no fd at all: CPython's child stub pickles the exception down the errpipe
   and the parent re-raises it *from the `Popen(...)` call*, which is the argument this card
   already makes at lines 88-94. Do not read (1b) as "stderr was the channel that got closed"
   for that case — there is no stderr message in it.

   **⇒ The replacement instrumentation for row 2:** bind the exception
   (`with pytest.raises(...) as ei`) and print/attach `ei.value.stderr` — the text the test
   already receives and throws away. `text=True` (`:145`) means it is `str`, `''` when the
   child printed nothing, never `None`. A probe edit under the revert rule in Notes, not a fix.
   **The EDIT needs no load; the MEASUREMENT still needs a failing run** — and 14 tries just
   showed one cannot be produced on demand. Running it on a passing run yields `''` and proves
   nothing; its value is that the NEXT failure stops discarding its own evidence.
   *One hazard to check when it does fire — speculation, labelled as such:* the post-kill
   `proc.communicate()` at `:157` has **no timeout** and returns only at EOF on both pipes,
   which needs every holder of the write ends to exit — the backgrounded grandchild inherits
   fds 1 and 2. `start_new_session=True` (`:142`) puts the tree in one group so `killpg` should
   reach it, **but there is a concrete path where no signal is sent at all**:
   `_kill_process_group` opens with `os.getpgid(proc.pid)` inside `try/except
   ProcessLookupError: return` — if the direct child has already been reaped, it returns
   *before* `killpg`, leaving a live grandchild holding the pipe. Then the drain blocks, the
   test hangs instead of raising, and `ei.value.stderr` is never reached.
   ~~`-n auto` cannot help either: xdist does not support `capture=no`.~~ **REFUTED —
   `capture=no` is ACCEPTED *and* HONORED under xdist. Measured 2026-09-04 18:44 with a
   3-arm probe** (`/tmp/test_xdist_marker.py`: a test that spawns `sh -c 'echo MARKER >&2'`
   with inherited fds, then writes its own marker):
   | arm | child marker | parent marker |
   |---|---|---|
   | `-n 2 -s` | **visible** | visible |
   | `-n 2`, no `-s` | absent | absent |
   | serial `-s` (control) | visible | visible |
   The `-n 2 -s` vs `-n 2` contrast is the discriminator: a silent downgrade would have made
   arm 1 look like arm 2. It does not. **So "inside the full suite, with `-s`" is a runnable
   configuration in which an inherited-fd child's stderr does reach the output — the exact
   missing measurement for row 1.**
   *Scope of "honored": measured at `-n 2` with a single test of one shape.* Whether every
   worker in an `-n auto` full-suite run under load forwards it identically is **untested** —
   and that is precisely the configuration this is wanted for.
   *My first version of this line said "REFUTED" on the strength of three SILENT tests exiting
   0, which was compatible with the very downgrade it claimed to refute — an unverified claim
   swapped for a differently-unverified one. The 3-arm probe is what makes the word honest.*
2. ~~Read `_enforce_spawn`~~ **DONE 2026-09-04 18:22 — read, INCONCLUSIVE, no lead. The last
   unread function in the path is now closed without naming a cause.** (Definition is
   `tests/sandbox_guard.py:691`; `:726` is its call site inside `guarded_init` — the old
   citation named the caller.) It calls `record_spawn`, returns early when `_audit_target()`
   or when `deny_roots_from_env()` is empty, and on a denied verdict calls `record_denial`
   then **raises `SandboxViolation`** — in the PARENT, *before* `original_init` runs. So a
   denial **cannot produce a `Popen` the caller can hold** (the instance exists — `guarded_init`
   IS `__init__`, so `self` is already allocated — but the constructor expression propagates
   and the caller binds nothing). Against the failure shape this card records as measured at
   lines 91-94 — a live `Popen`, a readable `returncode`, the poll loop exhausting, the error
   landing at `read_text()` — denial is dead for a second, independent reason: not just "would
   raise not SIGKILL", but "would leave the caller no `Popen` to read a `returncode` off".
   *The narrower form is deliberate:* "cannot produce the observed shape **at all**" would need
   the exception to reach the test, and `record_denial`'s own docstring warns that a
   swallow-all wrapper (`state.run_subprocess`) can make a `SandboxViolation` vanish. **Checked
   for row 2: `capture_one` has no such wrapper** — its only `except`s are `OSError` on the
   pidfile and `TimeoutExpired` on `communicate`, so a violation would propagate and the test
   would fail as `SandboxViolation`, not `FileNotFoundError`.
   *One correction to Q8PNPRTW's dead list while here:* `_harden_child_env` IS on row 2's path
   (`guarded_init:724` applies it whenever `env is not None and not shell` — `{}` is not
   `None`, so `env={}` reaches it; a truthiness test would have skipped it). Its "DEAD" verdict
   therefore rests entirely on the `:350` unchanged-return, **not** on the call being skipped —
   and that return does fire: **verified**, row 2's argv is `[str(fake_capture.sh)]`
   (`tests/test_capture_all_logins.py`, `monkeypatch.setattr(cal, "_capture_cmd", ...)`), and
   `_is_python_spawn("fake_capture.sh", ".../fake_capture.sh")` is False on all three of its
   tests. Had the test used the real `_capture_cmd` (argv[0] `uv`, which `_is_python_spawn`
   matches explicitly) the verdict would have collapsed.
   *(The `_SPAWNED_PIDS` "weak positive signal" that used to be cited here is WITHDRAWN — a
   set of ints exhausts nothing; it qualified only by matching the serial-vs-xdist shape.)*
3. Only then: instrument to separate (a) never exec'd / (b) exec'd then died / (c) exec'd but
   writes failed. Note (a) is already near-excluded by the errpipe argument.

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
