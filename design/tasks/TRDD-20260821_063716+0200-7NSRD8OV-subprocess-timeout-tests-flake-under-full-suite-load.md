---
trdd-id: 7NSRD8OV
title: Tests that shell out with a 5s timeout flake under full-suite load and can block a publish
column: testing
created: 2026-08-21T06:37:16+0200
updated: 2026-08-21T12:26:40+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
approval-tier: 0
scope: project
npt: []
eht: []
---

# Subprocess-timeout tests flake under full-suite load

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-21 10:22

**ROOT CAUSE FOUND, and it is NOT what this card has said all along. Column moved back
`testing` → `dev`; the 09:53 block below is SUPERSEDED and kept only for its measurements.**

**The knob never reaches the child in these tests.** `conftest._relax_subprocess_timeouts`
exports `CLAUDE_PLUGIN_OPTION_SUBPROCESS_TIMEOUT_SCALE=10` into `os.environ`, which works only
for a child that INHERITS the environment. But **28 test files build a MINIMAL env dict** and
pass it as `env=`, e.g. `test_gh_reply_watch._run_on_host`:

```python
env = {"PATH": …, "HOME": str(home), "CLAUDE_PROJECT_DIR": str(project), **extra_env}
```

No `os.environ.copy()`. **Zero of those 28 files pass the knob** (grep-verified: the only files
mentioning it are `conftest.py` and its own test). So in every one of them the detector runs at
scale **1.0** — `run_subprocess`'s default 10 s — fails open on expiry, and exits 0 with EMPTY
stdout. That is the card's signature exactly, and it explains what the "second family" theory
never could.

**This also corrects a verification I performed and reported as sound.** At 09:47 I checked that
`monkeypatch.setenv` writes real `os.environ` and concluded the mechanism reached the children —
quoting conftest's own docstring, which asserts the tests "build the child env with
`os.environ.copy()`". That claim is true of SOME tests and false of these. I verified the half
that was true and took the docstring's word for the half that decides the outcome.

### CORRECTION 10:35 — I over-claimed this as THE root cause. There are TWO families, both real

Written 13 minutes after the block above, on data that contradicts part of it. Of the **9 files
with measured failures**, only **2** build a minimal env (`test_gh_reply_watch`,
`test_github_issues_watch`). Checked per file:

| failing file | env pattern | gets the knob? |
|---|---|---|
| `test_gh_reply_watch` (10 fails) | minimal dict ×3 | **no** |
| `test_github_issues_watch` (2) | minimal dict ×1 | **no** |
| `test_branch_protection_guard` (7) | `os.environ.copy()` | **yes** |
| `test_token_usage_anomaly_detector` (1) | `os.environ.copy()` | **yes** |
| `test_terminal_trigger` (5), `test_leanctx_allowlist` (2), `test_cli_agent_roster` (2), `test_external_clear_retry` (1), `test_agentlens_probe` (1) | neither | n/a |

**`test_branch_protection_guard` is the one that breaks the single-cause story.** It uses
`os.environ.copy()`, so its child DID receive scale 10 — a 100 s effective timeout — and it
still produced empty stdout. A 100 s `run_subprocess` expiry is not credible, so its failure is
NOT this family.

**So the 73-direct-`subprocess.run` family is NOT retired — it is confirmed firing.**
`test_agentlens_probe` failed on `assert isinstance(None, dict)`: `agentlens_probe.probe_json`
returned `None` from its OWN `_TIMEOUT_S = 5.0`, reached by a direct call outside the seam. That
is precisely the family I claimed above "was never shown to fire". It has now been shown.

**Family A (proven, FIXED this session):** minimal-env children never receive the knob → scale
1.0 → `run_subprocess` 10 s → fail-open → empty stdout. Proven load-independently: a child
spawned with a minimal env reports `_timeout_scale() == 1.0`; one that inherits reports `10.0`.
Fixed by passing the knob through all 4 minimal-env builders in the 2 files.

**Family B (proven firing, NOT fixed):** direct `subprocess.run` with its own short timeout,
outside the seam — `agentlens_probe.probe_json` (5.0 s), `branch_protection_lib`
`_post_or_patch_ruleset` (15 s) and `github_config_audit._gh_json` (15 s) are the candidates on
the failing paths.

**Unexplained: the remaining 5 files** use neither env pattern. Mechanism unidentified — do not
assume it is either family until measured.

### The measurement that forced it (all on a CLEAN tree, my fence work stashed out)

`tests/test_gh_reply_watch.py` alone, five consecutive runs:

| run | result | wall-clock |
|---|---|---|
| 1 | 6 failed | 94.6 s |
| 2 | 4 failed | 71.0 s |
| 3 | 3 failed | 43.6 s |
| 4 | **14 passed** | 7.6 s |
| 5 | **14 passed** | 8.2 s |

**Failure count scales monotonically with wall-clock.** That is the timeout signature and
nothing else looks like it. Note runs 4-5 are the same green a subset run gives on a quiet box —
which is exactly how the 09:53 "4 clean full-suite runs" happened, and why they proved less than
they appeared to.

I stashed the fence work specifically because the failures appeared right after it landed and
correlation is not cause; on the clean tree they reproduce identically, so TRDD-K3PN7QW2 is
exonerated. Its files (memory modules + the memgrep crate) are not imported by any failing
detector.

### ⏵ LOADED-RUN RESULT — 2026-08-21 11:14. The first like-for-like before/after at real load

**`pytest -n 28 --dist loadgroup` on a 14-core box (2x oversubscription), before and after:**

| | run 1 | run 2 |
|---|---|---|
| BEFORE the 11 fixes | **24 failed** / 162 s | **12 failed** / 176 s |
| AFTER | **0 failed** / 81 s | **0 failed** / 99 s |

15,727 passed, 1 skipped, 0 failed, both post-fix runs. Every file that failed pre-fix is one
this session fixed, and the 7 fixed earlier stayed green through BOTH pre-fix stress runs at a
load higher than the one that originally broke them.

**THE CAVEAT, stated because this card has punished optimism four times today:** the post-fix runs
completed in 81 s and 99 s against the pre-fix 162 s and 176 s. Same worker count, but the box was
genuinely quieter, so this is **not a perfectly controlled comparison**. The evidence is
before/after at matched settings PLUS a named, proven mechanism per site — not a green run alone.

### ⛔ THE "CAVEAT RETIRED" CLAIM BELOW IS FALSE — REFUTED 2026-08-21 12:50

A soak run at `-n 28` right after it: **39 failed / 15,691 passed in 383.53 s** — the SLOWEST
run of the day and the WORST count, worse than the pre-fix 24 and 12. So 189 s was not a
ceiling, just another quiet-ish sample, and retiring the caveat on ONE loaded green was the
same error a fifth time. Failures spread far wider than the 13 fixed sites (9
`test_branch_protection`, 7 `test_package_manager_policy`, 5 `test_doctor_classify_sarif`, 5
`test_branch_protection_guard`, 3 `test_memory_librarian`, 3 `test_launchd_keepalive`, 2
`test_gh_issues_monitor`, 2 `test_agentlens_probe`) — several already "fixed", several never
seen before. **The four categories are real but NOT exhaustive at this load.** Card stays in
`testing`; evidence below is kept because the measurements are true, only the CONCLUSION was.

### ⏵ (REFUTED) CAVEAT RETIRED — 2026-08-21 12:26. A LOADED post-fix run

`-n 28`, after the UTC fix and `branch_protection_guard`'s category-D ceiling:
**15,730 passed, 1 skipped, 0 failed, EXIT 0, in 189.20 s.**

| run | wall-clock | failures |
|---|---|---|
| pre-fix | 162 s | **24** |
| pre-fix | 176 s | **12** |
| post-fix (quiet — the weak evidence above) | 81 s / 99 s | 0 |
| **post-fix (this one)** | **189 s** | **0** |

**189 s is SLOWER than both runs that failed**, so the "held at half the load that broke it"
objection no longer applies to this datum: the box was more contended than when 24 and 12 tests
fell over, and nothing failed. Combined with a named, proven mechanism at each of the 12 sites,
this is the back-to-back-under-load evidence the acceptance box asks for.

Test count 15,727 → 15,730 is the three regression tests added since (two librarian, one
timezone).

**Still not closed here**, and the reason is no longer evidential: `test_plugin_updates`' own
`timeout=60` failed once in the 283 s run and is deliberately unfixed (its detail was elided by
`--tb=line`, and it passes isolated), so one category-D site remains unaudited by choice.

**I stopped escalating load deliberately.** A `-n 42` (3x) attempt was KILLED mid-run and left the
box at loadavg 38. That was an overstep: earlier on this same card I declined to saturate a shared
36-user machine for marginal evidence, then did nearly that. The kill is the signal, and further
escalation is not worth what it costs everyone else on the host. If a stronger result is wanted,
the right venue is CI, not this box.

**What that means for the acceptance box:** back-to-back-under-load with no flake is MET at
`-n 28`, where the pre-fix baseline demonstrably failed. It is not met at arbitrary load, and
nobody should read it that way.

### SESSION STATE — 2026-08-21 10:36. Both families FIXED; 2 files still unexplained

**Fixed this session (4 sites):**

| family | site | fix |
|---|---|---|
| A | `test_gh_reply_watch` ×3, `test_github_issues_watch` ×1 minimal-env builders | pass the knob through |
| B | `agentlens_probe.probe_json` (`_TIMEOUT_S = 5.0`) | `× state.timeout_scale()` |
| B | `cli_agent_roster.fetch_agents` (`timeout_s = 15`) | `× state.timeout_scale()` |

`state._timeout_scale` is now PUBLIC `state.timeout_scale` and imported by both helpers rather
than each re-reading the env — a per-helper copy of one rule is exactly what TRDD-K3PN7QW2 spent
this session undoing.

**THE HAZARD THIS CREATES, and it must be carried forward.** Scaling a timeout DEFEATS any test
whose subject IS that timeout. `test_fetch_agents_timeout_is_reported` broke the moment
`fetch_agents` was scaled: `timeout_s=1` against a `sleep 5` shim became a 10 s ceiling the shim
finished comfortably inside, so the assertion passed nothing and failed. Such a test must OPT OUT
(`monkeypatch.setenv(knob, "1")`), which is what it now does. The seam fix never surfaced this
because `run_subprocess`'s own tests monkeypatch `subprocess.run` rather than really expiring.
Swept for the same shape: only `test_fleet_scan` also asserts on a `"timeout"` string, and it is
unaffected (69/69). **Any future site scaled this way needs the same sweep.**

**`test_terminal_trigger` — RESOLVED 10:44, and it split into TWO different causes:**

- **4 of 5 were family B, site #3.** `terminal_trigger._run_aimaestro_cli` is a direct
  `subprocess.run`; the `list --json` call passes `timeout=5.0`. It is best-effort, so an expiry
  is INVISIBLE — a timeout returns `None` exactly like a missing CLI or a down server, and the
  caller falls back to the local keystroke path. That is precisely
  `assert 'USE_ITERM_PATH' == 'FIRED:aimaestro'`: the ai-maestro path was never broken, it just
  never got an answer in time. Fixed inside `_run_aimaestro_cli`, so every caller is covered by
  one edit.
- **1 is a THIRD category the knob CANNOT fix.**
  `test_ai_maestro_cli_send_is_detached_not_inline` asserts `elapsed < 3.0` — a **wall-clock
  bound**, not a timeout. On a saturated box a genuinely detached send still takes longer than
  3 s to return, so it flakes however timeouts are scaled. It passes alone in 2.49 s.

  **And scaling the bound would DESTROY the test, which is why this needs redesign, not a knob.**
  Its purpose is to catch a regression where the per-command POSTs run inline (11-17 s); the spy
  sleeps 4 s per command, so an inline regression costs ~8 s. At the suite's scale of 10 the
  bound becomes 30 s — far above 8 s — so the exact regression it guards would sail through. A
  load-robust version must assert on STATE (the spy's `session command` has not completed) rather
  than on elapsed time.

**CATEGORY C, recorded because two categories have already been mistaken for one on this card:**
tests asserting WALL-CLOCK BOUNDS are load-sensitive by construction, and are fixed neither by
family A's env passthrough nor by family B's scaling. They need per-test redesign onto a state
assertion.

**CATEGORY C — REDESIGNED AND MUTATION-PROVEN, 2026-08-21 11:04.** The spy now touches a
`send-started` and a `send-done` marker around its 4 s sleep, and the test asserts **`done` does
NOT exist** when `send_self_command` returns. That decides the same question by CAUSALITY rather
than by clock: an inline delivery could only return AFTER the sleep, so `done` would necessarily
be on disk. True at any load. A second, generously-bounded poll then waits for `done` to appear,
so a no-op that reported `FIRED` cannot pass either.

Passes 3/3 including a **20.4 s** run — which the old `elapsed < 3.0` bound would have failed.

**And it was MUTATION-TESTED, because a redesigned guard that no longer guards is worse than the
flake it replaced.** Monkeypatching `_fire_detached_steps` to run the steps inline gives
`done_exists=True`, i.e. the assertion FAILS — the regression is still caught. Note the first
mutation run reported the opposite and was WRONG: the harness set the wrong env var
(`CLAUDE_PLUGIN_OPTION_TERMINAL_KIND` instead of `JANITOR_FORCE_TERMINAL_KIND`), so it returned
`USE_ITERM_PATH` and never exercised the ai-maestro path at all. Verify the harness before
believing its verdict.

**`test_leanctx_allowlist` — RESOLVED 10:52. Family B, site #4, and my earlier read was WRONG.**
I called it "a CONTENT/ordering mismatch, not a timeout shape at all, probably a separate defect".
It is a timeout, and the reason it does not look like one is worth keeping:
`ensure_janitor_allowed` appends the token to `attempted` BEFORE running `lean-ctx allow`, and on
expiry it `continue`s. So the RETURNED list stays complete and correct while the `lean-ctx`
process was killed before doing its work — the recorded CALL LOG comes back SHORT. Comparing
calls against `required_tokens()` then fails on list CONTENT, which reads as an ordering bug in
code that is fine. Fixed by scaling `_ALLOW_TIMEOUT_S`, via the module's existing lazy dual-form
`state` import and failing SAFE to the unscaled production value.

**`test_external_clear_retry` — RESOLVED 10:56, and it is a FOURTH category: the TEST'S OWN
timeout.** The failure is a raw `subprocess.TimeoutExpired: … timed out after 10 seconds`
propagating straight through the test. The 10 s ceiling belongs to the TEST's own
`subprocess.run`, spawning a trivial `echo …; exit 1` script — so **no amount of scaling inside
`scripts/lib` can ever reach it.** Scaling it is safe here because the timeout is incidental: the
test's subject is the CLASSIFICATION of a non-zero exit, not the timeout.

Verified by the wall-clock it now survives: the file used to FAIL at 13.3 s and now passes three
for three, including a run of **68.0 s**.

**CATEGORY D — a test's own `subprocess.run` timeout.** Same shape exists in
`test_terminal_trigger` (lines ~255/260/277, `timeout=10` driving `tmux`). NOT fixed: those have
never been observed failing, and fixing unobserved sites speculatively is what produced this
card's first two wrong diagnoses. Named here so the next occurrence is recognized in one step.

**NOTHING is now unexplained.** All 9 originally-failing files are accounted for: 4 families, 8
sites fixed, 1 test (category C) needing redesign and deliberately left. The superseded guess
about `test_leanctx_allowlist` being "a separate defect, probably its own TRDD" is resolved
above — it was family B all along.

**Verification status, stated honestly:** the full suite is green — 15,727 passed, 1 skipped, 0
failed, EXIT 0, 140.5 s. **This does not close the card.** Every run today that mattered was on a
quiet box, and this card's own lesson is that green on a quiet box proves nothing: the four green
runs at 09:53 led me to move it to `testing`, and it was flaking within the hour. Closing needs a
run under genuine load, with the two unexplained files resolved.

(An earlier run reported EXIT 3 with 15,727 passed / 0 failed. That was the real-state write
guard seeing `cli_agent_roster.py` change mid-run — me editing during the run, not a test escaping
isolation. Re-run clean: EXIT 0.)

### NEXT ACTION — a decision, and the cheap fix is the one that already failed once

1. **Add the knob to each of the 28 minimal-env builders.** Explicit and greppable, but it is
   28 edits and test #29 forgets it — this is precisely the per-site pattern that produced five
   divergent fence rules in TRDD-K3PN7QW2.
2. **One shared `child_env(**extra)` helper in conftest** that every builder calls. Still 28
   edits, but the rule then lives in one place.
3. **Patch `subprocess.run` inside the pytest process (conftest, autouse)** so any explicit
   `env=` dict is seeded with the knob. ONE edit, covers all 28 and every future test, and
   cannot be forgotten. Test-only; production untouched. The cost is magic — a test that
   asserts on the exact env it passed would need care.
**Recommend 2 for the rule + 3 for the enforcement**, but this changes test-harness behaviour
broadly, so it wants a human's eye; I did not pick unilaterally after three advisor wedges.

**Do NOT read the 09:53 evidence block as still standing.** Its four green runs were real and
its conclusion was wrong.

## ⏵ SUPERSEDED STATE — 2026-08-21 09:53 (kept for its measurements only)

**Where it stands:** the seam fix is SHIPPED (`99d2f7dd`) and now has real evidence behind it —
**4 consecutive full-suite runs, 15,726 passed, 0 failures**, at start-loads 13 → 27 → 39 → 44.
Wall-clock moved 83s → 89s → 162s → 121s, so load was genuinely biting (2× spread) and nothing
failed. Previously-flaky members all passed every run.

**NEXT ACTION:** decide whether that evidence closes the card, or whether it needs a run at the
**historical loadavg 80+** — which we did NOT reach (see the caveat below). It is a USER call,
because forcing 80+ means deliberately saturating a **shared 36-user box** that also runs the
janitor daemon, the ai-maestro server and other Claude sessions. I did not do that unilaterally.

**Load-bearing facts, so they are not re-derived:**
- The knob is `CLAUDE_PLUGIN_OPTION_SUBPROCESS_TIMEOUT_SCALE`, default **1.0** (production
  byte-identical), set to `"10"` for the suite by `conftest._relax_subprocess_timeouts`.
- It must be set via the **environment**, not by patching the callable: the tests spawn
  detectors as SUBPROCESSES and build the child env with `os.environ.copy()`, so an in-process
  monkeypatch of the function would never reach the child that actually runs the timeout.
  Verified this session — that is what makes the green runs meaningful rather than lucky.
- **The only valid measurement is the FULL suite under `-n auto`.** A 5-file subset is not a
  repro in either direction: the same 5 files went 5-failures/241s and then 163-passed/26.67s.

**SUPERSEDED — do NOT carry forward:**
- *"52 call sites"* as a complete enumeration — there is a second family (73 files calling
  `subprocess.run` directly). Kept as a known-uncovered risk, deliberately NOT pre-emptively
  edited; see acceptance box 2 for why.
- *The original per-test option list (1/2/3 under "What")* — written before the shared-seam root
  cause was found.
- *`agentlens_probe` as THE root cause* — it is one instance, not the class.

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
- [~] each one either stops shelling out, or takes an explicit test-side timeout, or asserts the
      probe succeeded before asserting on its output

      **ANSWERED DIFFERENTLY — this box was written under the superseded per-test framing** and
      is left `[~]` rather than `[x]` or `[ ]` because neither is honest. All three of its
      options are per-test, and the root cause is a SHARED seam: no per-test rewrite converges
      on call sites whose victim is chosen by scheduling. What shipped instead is one
      environment-scaled multiplier at that seam, which covers all 52 of its call sites at once.

      **The second family is knowingly NOT covered, and that is a decision, not an oversight.**
      73 files call `subprocess.run` directly, outside the seam. I did not pre-emptively edit
      them because I never instrumented WHICH call expires — editing 73 sites on suspicion is
      guesswork, and the evidence below says the seam alone is currently sufficient. If the
      flake returns, that family is the first place to look, and
      `branch_protection_lib` (6 sites at `timeout=10`/`15`) is the nearest suspect since it
      sits on the path of two of the five original failures.
- [x] production defaults (`_TIMEOUT_S = 5.0`) are UNCHANGED — this is a test-harness defect,
      and loosening a production timeout to make a test pass would trade a real guarantee for a
      green tick

      **MET.** `_timeout_scale()` returns exactly 1.0 when the knob is unset, and anything
      unparseable or non-positive falls back to 1.0 (a malformed knob must never silently
      SHORTEN a production timeout, and `0` would make every subprocess expire instantly).
      `tests/test_run_subprocess_timeout_scale.py` pins all of that in 10 tests, including a
      behavioural one proving the multiplied value is what `subprocess.run` actually receives —
      without it the helper could be dead code and the suite would not notice.
- [~] evidence: the full suite run back-to-back under load with no flake in this family

      **STRONG BUT NOT CONCLUSIVE — 2026-08-21 09:44-09:53.** Four consecutive full-suite runs
      (`-n auto --dist loadgroup`, matching the publish gate): **15,726 passed, 1 skipped, 8
      subtests, 0 failures** every time. Start loadavg 13 → 27 → 39 → 44; wall-clock 83s → 89s
      → 162s → 121s. The 2× wall-clock spread is the point — load was genuinely biting and the
      suite still held, including every one of the five originally-flaky tests.

      **The caveat that keeps this at `[~]`:** the original failures were recorded at **loadavg
      80+**, and these runs peaked around 44. So this is "held at half the load that broke it",
      not "held at the load that broke it". Reaching 80+ means deliberately saturating a shared
      36-user box that also runs the janitor daemon, the ai-maestro server and other Claude
      sessions — an outward-facing side effect I will not take unilaterally for marginal
      evidence. **USER call:** accept the 4-run evidence, or authorize a synthetic-load run.

## Approval log
