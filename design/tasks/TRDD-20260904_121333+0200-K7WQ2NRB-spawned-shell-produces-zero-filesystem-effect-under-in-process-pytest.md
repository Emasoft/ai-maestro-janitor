---
trdd-id: K7WQ2NRB
title: a spawned shell produces zero filesystem effect under in-process pytest — capture_all_logins rows 1 and 2
column: backburner
review-after: 2026-09-19
created: 2026-09-04T12:13:33+0200
updated: 2026-09-05T04:10:47+0200
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
implementation-commits: [6268dbeb]
external-refs: [TRDD-Q8PNPRTW]
---

# A spawned shell produces zero filesystem effect under in-process pytest

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-05

- **THE BUG.** Two tests in `tests/test_capture_all_logins.py` — `test_kill_process_group_…`
  (row 1) and `test_capture_one_kills_the_whole_tree_…` (row 2). When they fail, the child
  produces **zero filesystem effect**. **Do NOT assume they share a cause** (Q8PNPRTW retracted
  that twice).
- **STATUS: INSTRUMENTED; NOT REPRODUCIBLE ON DEMAND.** `6268dbeb` landed the deliverable that
  never needed a reproduction — row 2 keeps its child's stderr instead of discarding it, so the
  next real failure carries its own evidence. **Reported APART, because they are different
  populations and this card has retracted config-confounded aggregates twice:** 14/14 in a
  2-test selection at load 19.5-36.3, and 30/30 full-suite `-n auto` at 89-187 s. **Neither
  reached soak9's regime.** *A summed "~44 runs" would only sound more conclusive than either
  half.*
  **BRUTE FORCE IS EXHAUSTED — as a SPEND, not as a finding.** 30 runs bought zero information
  and the marginal run buys the same. What the 30 bound is the failure's RATE in this regime;
  they do not show non-reproduction — these rows are known-intermittent (row 1: 1/3 solo in one
  batch, 0/4 in another). **The bound, computed rather than asserted:** 0 failures in 30 trials
  gives a one-sided 95% upper bound of **9.50%** (rule of three: 10%). More usefully, the
  likelihood of seeing 30 straight greens is **0.215 at a 5% rate, 0.042 at 10%, 0.001 at 20%**
  — so a 20% per-run rate is effectively excluded, while **5% is entirely consistent with what we
  saw**, and 5% still reddens a daily suite about once a week.
  **⚠ THE BINOMIAL ASSUMPTION THAT FAILS HERE IS *IDENTICAL DISTRIBUTION*, NOT INDEPENDENCE.**
  *(I first wrote "independence", which is wrong and self-contradicting: the census result one
  bullet down — no leakage between runs — is evidence trials DO NOT influence each other, i.e.
  evidence FOR independence.)* The runs spanned 89-187 s, so they sampled a SPREAD of machine
  states; if failure probability is a function of that state there is no single `p` for a
  binomial to estimate. What was computed is a ceiling on an average `p` across **an uncontrolled
  mixture whose composition was set by whatever my foreground work happened to be doing** — not a
  designed sample, and not one I can reproduce.
- **THE ONE LIVE UNKNOWN: the 8.6× wall-clock gap to soak9 (822.89 s vs 89-187 s) is
  UNEXPLAINED.** Load is argued against, not refuted. The environments demonstrably DIFFER (both
  soak runs report a `subtests` counter no tracked revision ever declared) — but 8 subtests
  cannot make 727 s. **Do not read the plugin finding as closure.**
- **TWO CONSTRAINTS ON READING THE EVIDENCE.**
  - Row 2's instrumentation covers the `FileNotFoundError` shape ONLY. Its prints sit after the
    `raises` block, so the predicted hang shape never reaches them. Row 1 has none and needs
    none (inherited fds; `--capture=fd` already reports its child).
  - A 0 in `survivors.log` excludes an orphaned xdist worker and a bare `sleep 600`, and
    excludes **NOTHING about the `/bin/sh …fake_capture.sh` parent shell** — the census does not
    match it. Add `|/bin/sh .*fake_capture\.sh` on the next launch.
- **DO NOT re-run the suite hoping for a failure.** That is ~44 runs of precedent, and every one
  of the 30 full-suite runs finished in 89-187 s while the run that FAILED took 822.89 s — the
  loop never entered that regime, so more iterations of it sample the wrong population. A
  load-sensitive experiment also cannot be run on a box while a session does foreground work.

## Process notes and card history (background — not the first thing to read)

- **WHY `backburner` AND NOT `todo`.** `todo` is the PULL QUEUE — it advertises "available to
  work", and the board view, not the card, is what anyone scans; held there, the column asserted
  the opposite of this block. **⚠ `backburner` IS THE LEAST-WRONG OF THREE IMPERFECT COLUMNS,
  NOT A CLAIM THIS WAS DEFERRED BY DESIGN — do not cite this card as precedent for parking live
  work.** The case against it: this card was split OUT of Q8PNPRTW because *"parking live
  technical work behind a human decision that has nothing to do with them would hide them"*, and
  an unreproducible failure is the same SHAPE as a waiver. The drain rule's only licence to sit
  still is `blocked` with a true `blocked-by:` — which no TRDD provides here — so the honest
  reading is *"this card has no licence to sit still"*, not *"use the column that needs none"*.
  What makes it defensible is not the column but this block: Q8PNPRTW's work was hidden because
  its state gave no reader a way to see it.
- **`review-after:` SNOOZES; it does not resurface.** VERIFIED in the implementation, not just
  the rule text: `scripts/detectors/trdd-drift.py:56` says a `backburner` TRDD is drift-eligible
  *on purpose*, and `review_after_epoch` (`:605`) skips the card only while `now < review_after`
  — its docstring calls it "a SNOOZE, not a mute". So the field SUPPRESSES attention until
  2026-09-19, after which the card returns to where it already was. (`:615` exempts a
  `backburner` card carrying `blocked-by:`/`npt:`; this one has neither, which is why the field
  was needed at all.)
- **⇒ THE LOOP FINISHED: 30/30 GREEN, AND THAT IS THE STEP-0 RESULT.** Zero non-zero exits, zero
  entries in `unrelated.log`, `survivors.log` or `slow-runs.log`. Durations **89–187 s, mean
  124 s**. Ledger: `reports/suite-failures/20260905_024917+0200-…/`.
  **What it establishes:** the failure did not reproduce in **30 attempts at 89–187 s**, which
  BOUNDS ITS RATE in this regime. *It does not show non-reproduction* — these rows are
  known-intermittent, so 30 greens are consistent with a rate under 10%. Brute force is exhausted
  as a SPEND. **Kept apart from the earlier 14/14 two-test runs on purpose:** summing them into
  "~44" re-merges the two populations this card spent three commits separating.
  **What it does NOT establish, and this is the sharper half:** every one of the 30 ran at
  89–187 s, and **soak9 — the run that FAILED — took 822.89 s.** The loop never once entered the
  regime the failure was observed in. So "the loop cannot reproduce soak9" now has 30 data
  points behind it rather than 3, and the reason is still that these are not samples from that
  population. The 8.6× remains UNEXPLAINED (see the load bullet above).
  **⚠ THE CENSUS RESULT IS NOT EVIDENCE ABOUT LINE 77, AND I FIRST WROTE THAT IT WAS.** I called
  "zero orphans after all 30 runs" a real negative result for the cross-run-state hypothesis. It
  is not. That hypothesis predicts leftover state from a FAILING or TIMED-OUT run — a `sleep 600`
  whose parent died mid-`communicate()`, a worker orphaned by a wedge. **All 30 runs exited 0 and
  reaped their own children by construction**, so the census observed that healthy runs clean up,
  which nobody doubted. The hypothesis was never in a position to be tested. Reading a passing
  run's silence as information is the same error this card corrects at (1c) — absence of a
  section is absence of output only for a run that FAILED.
  **⚠ BUT THE WITHDRAWAL ITSELF OVER-CORRECTED — the 30 runs DID establish something, just not
  line 77.** They establish that **the loop's own iteration boundary is clean**: 30 consecutive
  runs, each starting into the box the previous one left, with zero orphaned workers and zero
  `sleep 600` survivors. That is direct evidence the harness does not leak on the HEALTHY path —
  the live worry that `--kill-after=30` and the census were built for. **What it buys is modest
  and worth stating exactly:** it forecloses ONE alternative explanation for the run of greens —
  that an early leak put later runs in a degraded state where the bug could not fire.
  *(An earlier wording here said it is "what makes the 30 greens interpretable at all". That has
  the POLARITY BACKWARDS: leakage would confound a RED result — was it the bug or the pollution? —
  not a green one. A green run under leaked state is still a green run.)*
  Narrow claim, real result; it is line 77's FAILURE-induced leakage that went untested.
  **Also true:** the census is armed and positive-controlled (14 live / 0 post-kill), so it will
  speak the first time a run does fail — exactly like row 2's stderr. It still cannot see the
  `/bin/sh …fake_capture.sh` parent.
- **(Historic) A 30-RUN LOOP WAS RUNNING WHEN THIS CARD WAS BACKBURNERED** —
  `reports/suite-failures/20260905_024917+0200-…`, started 02:49:17, ~2 min/run, stopping on the
  first red run or at run 30. Recorded here because nothing outside a `reports/` dir said so.
  **Its ONLY trustworthy output is whether any run went red.** Its duration/load pairs are
  **UNINTERPRETABLE — not "contaminated", which is more than I can show**: `load_start` is
  dominated by the previous run's decaying tail, so the loop's own load and this session's
  foreground work are not separated. (Runs 1-5 in fact span 107-136 s across loads 15.7-26.6,
  with the FASTEST run at nearly the highest load — read straight, that is weak load-duration
  coupling, not a visible confound.)
- **THE HARNESS CHURN WAS THE FAILURE MODE.** Five commits, ~6 green runs, five launches each
  discarded to fix the harness, zero observations of the actual failure. Each fix caught a real
  defect that would have produced false data — but the pattern met the "two failed attempts →
  stop and rethink" bar. Do not relaunch the loop to improve it.
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
  unplaceable on the load axis. Each run's `1 skipped` cannot be either row — **a skip is not a
  pass, and both rows are inside `16416 passed`** (arithmetic, needing no run; a standalone
  `-rs` gave 16 passed / 0 skipped, but that only excludes a DETERMINISTIC skip and this card's
  subject is load-gated). Takes the full-suite cell from 2 points to 4 (soak8 PASS 11.39,
  soak9 FAIL 15.53); cannot narrow the cause — only a captured failure can.

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

0. **(ADDED 2026-09-05, ahead of the 13:00 order — not part of that reordering.)
   THE EXPERIMENT STEP 1a's SHAPE CANNOT PRODUCE — a full-suite loop with load sampling.**
   Step 1a burned 14 runs on a 2-TEST SELECTION and proved only that that configuration does
   not fail at load ≤36. The failing observations (soak9) are IN-CONFIG, i.e. the rows running
   inside the full-suite pytest process. So the experiment is: loop the FULL suite, sample host
   load throughout each run, and preserve every run's output — then a failure is caught in the
   configuration that actually fails, with its load on the record. ~~Expensive by construction
   (~12 min/iteration), which is exactly why the 4 in-config data points so far are worth
   counting before spending more.~~ **STRUCK — MEASURED FALSE, see immediately below.** Kept
   visible rather than deleted (it is the premise a later reader would otherwise reconstruct),
   but STRUCK rather than merely annotated: it argues for a DECISION — "worth counting before
   spending more" — in its own imperative voice, and a refuted premise leading a step is how
   the same misreading gets made a fourth time. A correction should not have to out-argue the
   sentence above it.
   **⚠ THE STEP'S OWN COST ESTIMATE ABOVE IS WRONG, AND THAT IS THE FIRST RESULT.
   MEASURED 2026-09-05T02:28: a green `-n auto` full suite is 77.53 s here — `16416 passed,
   1 skipped`, host load 5.35 → 14.34.** Not "~12 min/iteration": that figure is the SERIAL
   shape. So the runs this step calls "expensive by construction" cost ~80 s each, and the
   argument for counting the 4 existing points before spending more does not apply to this
   configuration at all.

   **⚠ MY FIRST READING OF THE GAP WAS THE CARD'S OWN CLASSIC ERROR, AND I RETRACT IT.** I
   wrote that soak9's 822.89 s vs a green 78 s meant "a green run is therefore NOT a sample
   from soak9's population" and blamed the difference on load — one paired observation, four
   uncontrolled variables, one blamed. That is (1a)'s warning, one screen below (1a). What the
   artifacts actually say, read first-hand (`/tmp/soak8.txt`, `/tmp/soak9.txt`,
   `/tmp/soak9.meta`, all still present — they were assumed lost):

   - **BOTH soak runs were slow, so it is not a one-off:** soak8 `11 failed, 16380 passed,
     1 skipped, 8 subtests passed in 906.91s`; soak9 `11 failed, 16391 passed, 1 skipped,
     8 subtests passed in 822.89s`. *And soak8 was NOT a clean run* — this card's line above
     calls it "soak8 PASS 11.39", true only of the two ROWS, never of the suite.
   - **The worker-count confound is CLOSED, in the direction that strengthens comparability:**
     soak9's tracebacks name `gw0…gw13`, i.e. 14 workers; `hw.ncpu` is 14 and today's run
     header says `created: 14/14 workers`. Same width.
   - **LOAD ARGUES AGAINST ITSELF HERE, BUT IS *NOT* REFUTED — and my first wording of this
     bullet was the same error a THIRD time.** I wrote "LOAD IS REFUTED … higher **ambient**
     load, 8.6× faster" from our 22.79-start / 95.50 s run vs soak9's 15.53-start / 822.89 s.
     **"Ambient" is the word that was carrying the claim, and it is false.** The 1-minute
     average is a decaying 60 s window and this loop starts runs back-to-back, so a run's
     `load_start` IS the tail of the previous run's 14 workers — visible in the ledger, where
     run 1's `load_end` 18.43 is run 2's `load_start` **verbatim**. soak9's figure is the
     opposite kind of number: `/tmp/soak9.meta` reads `load averages: 15.53 16.00 15.44` —
     flat across 1 m/5 m/15 m, with 25 users logged in, i.e. genuinely sustained. Comparing a
     self-generated transient against sustained foreign load is exactly the apples-to-oranges
     move Q8PNPRTW `:224-226` was retracted for, inverted.
     *What survives:* a suite that started under a 22.79 instantaneous reading still finished
     in 95 s, which argues against a naive "high load ⇒ slow suite" story. Nothing is refuted.
     **The harness now records all three averages** (`1m/5m/15m` per ledger cell) so the next
     comparison has the figure that tells a tail from sustained load. Free — `uptime` already
     printed them.
     *An OBSERVATION that cuts the other way — deliberately not called a demonstration:* three
     green runs spanning 95.50 / 118.99 / 149.04 s as the box got busier. **This is not a
     controlled series and must not be read as one:** the first two are from one launch, the
     third from a different launch with a different harness, and the load that rose across that
     window was largely load *I* generated investigating — greps, `git log -S`, `uv run`,
     three probe runs of the suite itself. Three points rising in the order they happened to be
     run is the arrangement most likely to be over-read. Consistent with load mattering within
     this environment; it demonstrates nothing, and it still does not reach 822 s.
     *The experiment that would settle it, and it is cheap (~80 s a run):* N greens from ONE
     launch on an otherwise idle box, then N more under a deliberate CPU load generator. A
     manipulated variable and a control. Not yet run — and it cannot be run honestly while this
     session is doing foreground work on the same box, which is itself the reason the three
     points above are not a series.
   - **⇒ WHAT DID DIFFER, AND IT IS AN ENVIRONMENT DIFFERENCE, NOT A LOAD ONE: both soak runs
     report `8 subtests passed`.** That counter comes from `pytest-subtests`. It is NOT
     installed here (`pytest`, `pytest-timeout`, `pytest-xdist`), and the string `subtests`
     appears nowhere in `tests/`, `scripts/`, `pyproject.toml` or `uv.lock` **in any revision**
     (`git log -S`) — only in TRDD prose. So the soak-era plugin set is **not reproducible from
     this repo**, and the collected counts differ too (16403 then, 16417 now).
     **⚠ That `git log -S` had an unverified premise, since checked:** it proves nothing if
     `uv.lock` is untracked — an empty result and a vacuous search look identical, the same
     trap (1c) documents for the exit-2 collection run. **Verified 2026-09-05:
     `git ls-files --error-unmatch uv.lock` succeeds (TRACKED) and `grep -c subtests uv.lock`
     is 0**, so the search was real. Also checked: **no `subtests` dist-info in `.venv`** now.
     The residual explanation is an out-of-band `uv pip install` later wiped by a `uv sync`,
     which by construction leaves no git trace — consistent with everything observed, and
     neither confirmed nor excluded.
   - **⚠ THE PLUGIN FINDING IS NOT A CANDIDATE MECHANISM FOR THE 8.6×, AND MUST NOT BE READ AS
     ONE.** It sits directly after the load bullet, which invites exactly that reading — but
     `8 subtests passed` means eight subtests ran somewhere in 16 000, and no arrangement of
     that explains **727 seconds**. It establishes only that the two environments **differ**.
     **The cause of the wall-clock gap is UNIDENTIFIED.** Do not stop looking here.
     *Speculation, labelled:* a clean ~8-10× multiplier at identical worker count is the
     signature of per-bytecode instrumentation (coverage, a tracer), not of contention —
     contention shows up as variance and stalls, not a uniform factor. No evidence for it; it
     is simply the hypothesis this data most resembles. **Two caveats that weaken even that:**
     soak8 and soak9 differ from each other by 10% (906.91 vs 822.89), which is variance rather
     than a clean constant; and **the multiplier is inferred from two TOTALS, never from
     per-test timings** — and per-test timings are the measurement that would actually separate
     "everything 8× slower" from "a handful of tests stalling for minutes". Neither soak run
     appears to carry `--durations`, so that measurement is probably not recoverable from them.
   - *Not established, and deliberately not asserted:* whether slowness relates to the failure
     at all. What IS established is that a wall-clock comparison across that boundary compares
     two environments, so the honest status of "the loop may be unable to reproduce soak9" is
     **open**, not shown.

   Duration stays in the ledger as a cheap per-run regime proxy, and a PASSING run over
   `SLOW_RUN_S=250` now gets its own `slow-runs.log` line — a 400 s green run would be the
   first real evidence here and would otherwise read as an unremarkable row.

   **STARTED 2026-09-05T02:49:17+0200** (a start event, not a state — see the check below) —
   `scripts_dev/k7wq2nrb_full_suite_load_loop.sh` (gitignored; the harness is scratch, the
   numbers are the record). `uv run pytest -n auto`, `MAX_RUNS=30`, `RUN_TIMEOUT=1200`,
   `SLOW_RUN_S=250`, load sampled every 15 s, every run's full output plus a per-run `ps`
   snapshot kept under
   `reports/suite-failures/20260905_024917+0200-k7wq2nrb-full-suite-loop/`, with `ledger.tsv`
   (run/exit/load-start/load-end/duration/summary — each load cell is now **`1m/5m/15m`**, see
   the load bullet above) and, when they have content, `unrelated.log`, `slow-runs.log`,
   `survivors.log`. **Read `unrelated.log` with `sort | uniq -c`, not by scanning** — over 30
   runs the same known flake repeats and only a NEW name is worth noticing, which is why each
   line names its failing tests rather than only a run number and exit code.
   **Sibling dirs `…024041` = third launch, superseded harness, one green run (149.04 s at
   34.46 — *1-minute figure only, pre-dating the 1m/5m/15m change, so it carries the very
   defect the load bullet retracts*); `…024529` = fourth launch, superseded by the census fix.**
   **The sibling dirs, named absolutely so this stays true however many loops follow:**
   `…022821` = first launch, superseded harness, ONE green run at 77.53 s (the measurement
   above). `…023245` = deliberate `RUN_TIMEOUT=5` smoke test — its `exit 124` is THE CAP
   FIRING, never a hang in the suite. `…023305` = second launch, superseded harness, two green
   runs (95.50 s at load 22.79; 118.99 s at 18.43). `…023902` / `…023927` = deliberate
   `RUN_TIMEOUT=8` / `=45` kill probes, likewise cap-firings by construction.
   **VERIFY IT IS STILL ALIVE BEFORE BELIEVING THIS LINE** — nothing updates it when the loop
   dies, is killed by a session restart, or wedges: `tail ledger.tsv` and check the process
   table. A stale last row with no pytest running means the loop is dead and this paragraph is
   history.
   **It stops on the EXIT CODE, not on an output format.** The first version stopped on
   `^FAILED tests/test_capture_all_logins`, which exists only by virtue of pytest's `-r`
   default and is absent entirely from a timed-out or crashed run — a loop whose only exit
   lever is a rendering detail can burn its whole budget and stop on nothing. Now: non-zero
   exit stops it, and grep only CLASSIFIES the stop (timeout / capture_all_logins / some other
   test). **Exit 124 is a RESULT, not an accident** — it is the card's own predicted second
   failure shape (the untimed `communicate()` at `capture_all_logins.py:157` blocking on a
   grandchild that still holds the pipe, lines 384-392); uncapped, that shape would wedge the
   loop silently.
   **An UNRELATED red run does NOT stop the loop — it logs to `unrelated.log` and continues.**
   Stopping on any non-zero would have spent the whole 30-run budget on the first unrelated
   flake, and this suite has a documented supply of them (Q8PNPRTW's eleven; TRDD-CI9AC02Y is
   a whole card about `branch_protection` rows failing only in-suite). The stop decision is the
   CLASSIFICATION; `rc` is only what makes 124 detectable at all. A `STOP` file in the report
   dir halts it between runs.

   **What the cap is PROVEN to do, and what it is not.** `RUN_TIMEOUT=5` proved the shell
   branch (exit 124 → correct classification → break) and **no more** — it killed pytest during
   collection, where there is nothing to orphan, so calling that "end-to-end" (my previous
   commit's word) covered only the control flow. A second probe at **`RUN_TIMEOUT=45`,
   mid-suite with all 14 workers live**: the per-run `ps` snapshot showed **zero surviving
   `execnet` / `popen-gw` / `sleep 600` processes**. The chain `uv` → pytest → 14 execnet
   workers → `/bin/sh` → `sleep 600` does get reaped.
   **⚠ BY *TERM*, NOT BY THE `--kill-after` BACKSTOP — the ledger says so.** That probe's
   `duration_s` is **45**, the TERM deadline exactly; had the KILL been needed, `timeout` would
   not have returned until 75. So `--kill-after=30` contributed **nothing** to this
   observation and remains **untested insurance**. Crediting it (my previous wording) would
   tell a reader the backstop was exercised when it never ran.
   *Still NOT proven:* propagation when a worker is genuinely wedged draining a pipe — which is
   the case the cap exists for. A healthy worker is killable by construction.
   **⚠ AND THE CENSUS'S FIRST ANSWER WAS A FALSE POSITIVE — worth recording because it would
   have invented evidence.** It reported exactly one survivor: the `zsh -c` wrapper running the
   census, whose argv carries the search pattern. Snapshotting `ps` to a file defeats *grep's*
   self-match but not the *invoker's*. Uncorrected, it would have produced a standing non-zero
   survivor count — manufactured support for line 77's cross-run-state hypothesis, out of its
   own shell.
   **⚠ AND THE FIRST FIX WAS WORSE THAN THE BUG, WHICH IS THE PART WORTH REMEMBERING.** It
   filtered argv TEXT (`shell-snapshots|k7wq2nrb_full_suite`), trading a **loud** false
   positive for a **silent** false negative: any real orphan whose argv happened to carry the
   repo path would be dropped and the census would confidently print 0. A census that fails
   silently is worse than no census. It now discriminates on **identity and executable** —
   `awk` drops this script's own pid and its parent's, then the pattern anchors on
   `.venv/bin/python3` … or a command field that IS `sleep 600`.
   **⚠ AND THAT SECOND FIX WAS ALSO BLIND — measured, not argued.** It looked for
   `execnet|popen-gw` in argv. Snapshotting `ps` during a live 14-worker run shows an xdist
   worker actually is:
   `<repo>/.venv/bin/python3 -u -c import sys;exec(eval(sys.stdin.readline()))` — **execnet
   ships the real code over STDIN, so the token `execnet` is never in argv**, and `popen-gw` is
   a tmp DIRECTORY name that appears only inside tracebacks (which is where every sighting of
   it on this card comes from). So the pattern matched **nothing, ever**: a permanent silent 0,
   the exact failure the fix before it was written to prevent. Three versions, two of them
   unable to see the thing they counted.
   **The THIRD version matches the bootstrap SHAPE**, scoped to this repo's interpreter
   (`$REPO/.venv/bin/python3 -u -c`), plus the `sleep 600` arm. `$2!=me` was dropped as
   protection theatre — an orphan is reparented to init, so its PPID is 1, never this script's.
   **POSITIVE CONTROL, which is what makes the zero meaningful:** the new pattern finds
   **14** in a snapshot taken *while* a suite was running, and **0** in the 45 s probe's
   post-kill snapshot. Until that control existed, "zero survivors" was a statement about the
   instrument, not about the box.
   **⚠ AND THE OTHER HALF OF THAT CONTROL WAS INFERRED, STATED AS MEASURED, AND WRONG.** I
   wrote "the old pattern returns 0 for BOTH" without running it against the 14-worker
   snapshot. Run: it returns **1** — and the 1 is not a worker at all, it is the `zsh -c`
   wrapper whose argv quotes the pattern. So the old census would not merely have missed 14
   live workers; it would have **reported one survivor that did not exist**, and a session
   reading that count would have had false support for the cross-run-state hypothesis on a
   perfectly clean box. Silent blindness on the real thing, a phantom on the fake one, from
   the same regex.
   Row 2's instrumentation was landed FIRST, on purpose: a failure caught by a loop started
   before it would have thrown its evidence away exactly as every failure so far has.
   **⚠ SCOPE — the loop's stop condition is WIDER than the instrumentation's reach.** It stops
   on any red run, but the child's stderr is attached only for **row 2's `FileNotFoundError`
   shape**. Not for the hang shape (the prints are after the `raises` block, which never
   exits), and not for **row 1**, which got no instrumentation this turn — correctly, since it
   inherits fds and `--capture=fd` already reports its child (1c). Do not read a captured stop
   as "the stderr question is answered"; read the classification line first.
   **Why this does not violate step 1's "do not re-attempt by re-running the tests":** that
   prohibition rests on (1a), and the card brackets (1a) to the 2-test selection in its own
   words — *"licenses NOTHING about the full-suite configuration"*. Step 0 IS the configuration
   (1a) excludes itself from. Citing the card against itself, not reconstructing what a prior
   session meant.

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

   **⇒ LANDED 2026-09-05 — the row-2 instrumentation is in the tree, and NOT as a revertible
   probe.** `tests/test_capture_all_logins.py:322` now binds `as timeout_info` and prints
   `.stderr`/`.stdout` right after the `raises` block. **Why this one is exempt from the Notes
   revert rule:** that rule exists for probes that CHANGE the subject (the `.started` marker
   edited the child script). This changes no behaviour — it prints data the test already
   receives and threw away — and reverting it would guarantee the next failure again destroys
   its own only witness, which is the entire point of the step. Silent on the passing path
   (pytest reports captured stdout only on failure), so it costs nothing per green run.
   Module re-run after the edit: **16 passed in 12.90 s**; `ruff check` clean and
   `ruff format --diff` touches none of the new lines (the file's pre-existing reflow diff at
   `:84-145` is unrelated and deliberately left alone — the gate is check/mypy/pyright, not
   `format --check`).
   *Unchanged by landing it:* **the MEASUREMENT still needs a failing run.** On a passing run
   both fields are `''`.
   **⚠ THE EXEMPTION IS A SESSION JUDGMENT, NOT A CARD FINDING.** It is recorded in the same
   voice as the measurements above, and it is not one — no measurement says a rule does not
   apply. If a later session disagrees, `git revert 6268dbeb` is the whole undo.
   *And the Notes rule is now FALSE AS WRITTEN for this file* — it says every probe editing
   `tests/test_capture_all_logins.py` must be reverted, which would mis-instruct anyone who
   reads it after this commit. Corrected in Notes to name its actual subject: probes that
   CHANGE the thing under test.
   **⚠ COVERS ONE OF THE TWO PREDICTED FAILURE SHAPES.** The prints sit AFTER the
   `pytest.raises` block, so they run only if `capture_one` actually raised. In the hang shape
   this card predicts (lines 384-392) `communicate()` never returns, the block never exits,
   and the instrumentation contributes nothing — that run appears as a wedged worker, which is
   why step 0 now caps each run and treats exit 124 as its own observation.

   **⇒ The original wording of this step, for the record:** bind the exception
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

- Any probe that **CHANGES THE THING UNDER TEST** in `tests/test_capture_all_logins.py` — the
  `.started` marker edited the child script, and that is the shape this rule is about — MUST
  be reverted with the Edit tool and verified by an empty `git status --porcelain` +
  `git diff`. The git guard refuses `git checkout --` here, correctly.
  *(Narrowed 2026-09-05, and the narrowing is the exception's own justification, so weigh it
  as such: as written the rule said EVERY edit to this file must be reverted, which would have
  required reverting `6268dbeb` — an instrument whose only value is that the NEXT failure
  keeps its evidence, i.e. a rule reading that guarantees the gap it was meant to close. The
  hazard the rule actually guards is uncommitted probe state in a file the git guard will not
  `checkout --`; a committed, behaviour-neutral change is not in that class.)*
- Evidence: `reports/suite-failures/20260904_114209+0200-capture-all-logins-failure-state.md`,
  `reports/suite-failures/20260904_113039+0200-fixture-fork-latency.md`.
- **IF YOU STRIKE A REFUTED SENTENCE, THE PLAIN-TEXT MARKER CARRIES THE MEANING — the tildes
  are decoration.** `~~…~~` is GFM: it renders on GitHub and NOWHERE ELSE these cards are
  actually read — not in `cat`, `grep`, `less`, or an agent reading raw markdown, which is the
  majority case for this corpus. Step 0's struck lead clause is safe only because
  `**STRUCK — MEASURED FALSE**` sits beside it in plain prose. A strike-through without that
  marker is invisible to every reader who is not on GitHub, which is worse than not striking.
- **WHEN THE MECHANISM IS NAMED, COLLAPSE THIS CARD'S RETRACTION LAYERS** the way TRDD-34GB6XUI
  does for ZQ02QG1L — the load claim, the census, and the timeout scoping each carry three or
  four superseded readings now. **Not before then, and deliberately not as its own card yet:**
  34GB6XUI exists because ZQ02QG1L's layers were collapsed *after* the work settled, and here
  the same claims are still moving (the census changed twice in one session). Collapsing now
  would destroy the reasoning that catches the next wrong fix, and would be a rewrite of text
  that may need another. A second collapse TRDD before the first has run is speculative
  machinery.
