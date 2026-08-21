---
trdd-id: 7NSRD8OV
title: Tests that shell out with a 5s timeout flake under full-suite load and can block a publish
column: dev
created: 2026-08-21T06:37:16+0200
updated: 2026-08-21T09:42:24+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
approval-tier: 0
scope: project
npt: []
eht: []
---

# Subprocess-timeout tests flake under full-suite load

## Why

`uv run pytest` is the publish gate (`publish.py::_gate_tests`). A test that fails only under
the load the full suite itself creates will therefore block a publish at random, and — worse —
send whoever is publishing to debug a component that is not broken. Measured twice in one
session, on two unrelated tests:

1. `tests/test_pkg_manager_guard.py` timed out during a publish run at load avg 83; passed
   27/27 isolated immediately after.
2. `tests/test_window_burn_rate.py::test_agentlens_cause_prefers_cli` failed inside a 13-minute
   full-suite run; on the next full run the failure MOVED to
   `test_agentlens_cause_kept_when_material` in the same family; then 6 consecutive isolated
   runs of that file passed 54/54.

3. Same session, a later full run: `test_branch_protection.py::test_fires_when_unprotected`,
   `test_branch_protection_guard.py::test_apply_acts_when_only_one_baseline_present`, and
   `test_gh_reply_watch.py::test_first_fire_is_silent_and_baselines_the_cursor` failed together
   inside a 12m33s full run — **all three passed isolated in 8.37s**. That takes the class from
   "two odd tests" to **5 tests across 4 files**, which is the argument for fixing the CLASS
   rather than the instances: whichever subprocess lands in a slow window is the one that fails,
   so chasing individual tests will never converge.

## ⏵ ROOT CAUSE — measured 2026-08-21, and it CORRECTS this card's first diagnosis

**The original text below blamed `agentlens_probe.probe_json`'s 5.0s ceiling. That is true only
of the `test_window_burn_rate` instance.** Reading the three later failures IN FULL (rather than
pattern-matching them onto the first) gives a different and more general answer, and the
correction matters because the first diagnosis pointed at one helper in one module while the
real seam is shared by every detector in the repo.

**The signature is identical in all three: the spawned detector exits `returncode 0` with
COMPLETELY EMPTY stdout AND stderr** — the test then fails asserting `"BRPROT-001" in ''`, and
in the `gh-reply-watch` case no state file is written at all. The script ran and deliberately
did nothing. The outer harness timeouts are NOT involved and are generous (60s / 30s / 180s).

The real chain is one layer down:

1. Detectors call the SHARED helper `state.run_subprocess` (`scripts/lib/state.py:954`) with
   short per-call timeouts — `branch-protection.py:93` runs `git rev-parse --git-dir` with
   **`timeout=5`**, `gh auth status` with `timeout=10`.
2. `run_subprocess` returns **`None`** on `subprocess.TimeoutExpired`. This is CORRECT and
   deliberate production behaviour — its docstring says why: a hung subprocess must never park
   the 5-minute heartbeat.
3. The detector's next line is `if git_dir is None or git_dir.returncode != 0: return 0` — a
   silent, successful exit.

So under full-suite load (measured load avg 80+; the first instance at 83) a `git rev-parse`
exceeds 5s, the detector correctly fails OPEN, and the test sees nothing. **Fail-open is right
for production and is exactly what makes the test failure uninformative**: an empty-string
assertion gives no hint a timeout occurred, so the natural response is to go read detector logic
that is not wrong. The failure LOOKS like a logic bug and is a scheduling one.

This also explains the moving target better than the first diagnosis did: the seam is shared, so
whichever detector's short call lands in a slow window is the test that fails.

**Original (partially superseded) note follows.** `agentlens_probe.probe_json` has its own
`_TIMEOUT_S = 5.0` (`scripts/lib/agentlens_probe.py:54`) and the same fail-open-to-`None`
shape; isolated run times for `test_window_burn_rate.py` were measured swinging **3.7s →
13.3s** against that 5.0s ceiling. It is a second instance of the same class, not the class
itself.

## ⏵ WHERE THE LOAD COMES FROM — measured 2026-08-21 09:44, and it names the only valid repro

The card says "the load the full suite itself creates" without saying HOW, and that gap let me
spend a measurement on a repro that cannot work. Both halves now measured:

- **xdist is the load.** `pytest-xdist` is a declared dev dependency and the publish gate runs
  `_PYTEST_CMD = [… "-n", "auto", "--dist", "loadgroup"]` (`publish.py:187`). pyproject's own
  comment says why it was added: the suite is ~15k tests and ran **serially at ~16 min on a
  14-core machine**. So the gate shards across 14 workers — and a large share of these tests
  spawn a DETECTOR SUBPROCESS, i.e. a fresh Python interpreter plus its imports. 14 concurrent
  workers each spawning interpreters is what produces the loadavg 80+ the card records, and at
  that load a `timeout=5` on `git rev-parse` expires.
- **Therefore the 5-file subset is NOT a repro.** Run alone just now: **163 passed in 26.67s**
  at loadavg 12 — green. The earlier run of the SAME five files took **241s and failed 5**. Same
  files, same code, ~9× wall-clock: the difference is entirely what else was on the box. A
  subset run neither confirms nor refutes this bug, in either direction.

**Consequence for anyone continuing this card: the ONLY measurement that counts is the FULL
suite under `-n auto`.** A green subset proves nothing (it did not exercise the load), and a red
subset proves nothing either (the box may have been busy with something unrelated). This is also
the honest reading of the earlier "5 failures in 241s" — it is evidence the flake is real, not
evidence about which call site caused it.

Note this does NOT make xdist the defect. Sharding is deliberate and load-bearing (a 16-minute
serial gate is one people route around, which pyproject calls out). The defect is that
production timeouts tuned for the heartbeat are also the timeouts a saturated test box must
meet.

## What

**Superseded framing warning:** the options below were written against the first diagnosis (one
helper, `probe_json`, and a per-test rewrite). With the root cause corrected above, the fix
belongs at the SHARED seam — `state.run_subprocess` — because per-test rewrites cannot converge
on a class whose members are "whichever detector's short call lands in a slow window". Options 1
and 2 are per-test and therefore mostly the wrong shape now; option 3 (make it LOUD) still
stands on its own merits and is the part that turns an uninformative failure into a diagnosis.

The candidate at the seam: a timeout SCALE read from the environment, defaulting to 1.0 so
production behaviour is byte-identical, set once in `tests/conftest.py` for the suite. It works
because tests build the child env with `env = os.environ.copy()`, so the variable reaches the
spawned detector. **Approach under advisor review before implementation** (project rule: consult
before a significant change; this touches a helper every detector uses).

Not "raise the timeout until it stops" — that just moves the threshold and re-hides the problem
on a slower machine or a busier day. Original options, cheapest first:

1. **Do not shell out at all in these tests.** The probe's CONTRACT (parse JSON stdout, fail
   open) is what is under test; the fact that the JSON arrives via `/bin/sh` is incidental.
   Injecting the payload directly removes the timing dependency outright and makes the tests
   faster. This is the likely right answer for most of them — but check first whether any test
   is deliberately exercising the real `subprocess` path (argv splitting, non-zero exit,
   genuine timeout); those must keep a subprocess and get option 2 or 3.
2. **Make the test's timeout explicit and generous** where a real subprocess is required —
   `probe_json` already takes `timeout=` as a keyword, so a test can pass its own without
   changing the 5.0s production default.
3. **Fail loudly on timeout in tests**: assert the probe returned non-None before asserting on
   the clause, so a load flake reports "probe timed out" instead of an empty string. Cheap, and
   worth doing regardless of 1/2 — it converts a misleading failure into an honest one.

Sweep for the whole class, not just these two: grep the suite for tests that build a script in
`tmp_path` and invoke it through a production helper with a fixed timeout.

## Acceptance

- [ ] the class is enumerated (which tests shell out through a fixed-timeout helper), not just
      the two that happened to fail — **and the enumeration settles the design question.**

      **UNCHECKED again 2026-08-21 09:42.** It carried `[x]` from 08:10 until the second family
      below was found. Two claims live in this box and only one survived: the enumeration does
      settle the DESIGN question (a shared seam, not per-test — that holds and is durable), but
      the class itself is NOT fully enumerated, so the box as written is not met. Leaving it
      checked would have made a partial fix read as a finished one on the board.

      Counting PRODUCTION call sites (the seam, not the tests, because the tests are just
      whoever was unlucky): **52 `state.run_subprocess` call sites fail OPEN within 15s** —
      37 at 10s, 8 at 15s, and **7 at 5s**, which are the most exposed. The 5s tier:
      `branch-protection.py:93` (`git`), `fleet-github-config.py:52` (`git`),
      `tracked-ignored.py:65` and `:75` (`git`), `identify_environment.py:99` and `:144`
      (`ps`), `state.py:834` (`ps`). Add `agentlens_probe.probe_json`'s own `_TIMEOUT_S = 5.0`
      as an eighth, reached by a different helper with the identical fail-open-to-`None` shape.

      Those three 5s detectors alone are driven by 14 test files. So the class is not "two odd
      tests" and not even "five" — it is *any* test that drives *any* of those call sites while
      the box is loaded, and which one fails is decided by scheduling. **A per-test or
      per-call-site fix cannot converge on that**, which is why the fix belongs at a shared
      seam. This is the measurement that turned the card's original option list (all per-test)
      into the wrong shape.

      **⚠ THIS ENUMERATION IS INCOMPLETE — corrected 2026-08-21 09:20, and the correction is
      why the fix is only PARTIAL.** I counted one family: call sites going through
      `state.run_subprocess`. There is a SECOND family — **73 files call `subprocess.run`
      DIRECTLY**, several with their own timeouts, entirely outside that seam
      (`branch_protection_lib._post_or_patch_ruleset` at `timeout=15`,
      `github_config_audit._gh_json` at 15.0, `fleet_scan._run_probe_outcome` at 10,
      `agentlens_probe.probe_json` at 5.0, `fleet_restart` at 5, …). Scaling the seam does
      nothing for those.

      Measured after shipping the seam scale (`99d2f7dd`): the five previously-flaky suites run
      TOGETHER still produced **5 failures in 241s**, same empty-stdout signature, while the
      same test passes ALONE in 11.9s. I did not instrument which call expired, so the specific
      site is unproven — but the second family demonstrably exists and the flake survives.
- [ ] each one either stops shelling out, or takes an explicit test-side timeout, or asserts the
      probe succeeded before asserting on its output
- [ ] production defaults (`_TIMEOUT_S = 5.0`) are UNCHANGED — this is a test-harness defect,
      and loosening a production timeout to make a test pass would trade a real guarantee for a
      green tick
- [ ] evidence: the full suite run back-to-back under load with no flake in this family

## Approval log
