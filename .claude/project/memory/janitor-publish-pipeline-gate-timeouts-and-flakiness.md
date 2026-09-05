---
name: janitor-publish-pipeline-gate-timeouts-and-flakiness
description: "publish exited 3 but every test passed / rc=3 with nothing failing / the gate timed out but the test passes on its own / TimeoutExpired on an xdist worker / is this flaky or a real regression / the test gate blocks a publish at random / tests fail only in the full suite and pass alone / a detector exits 0 with empty stdout / assert something in an empty string / which load-flake category is this / should I scale every timeout call site or enumerate them / enumerating call sites keeps missing some / scale timeouts at a seam not per site / my timeout scaling looks applied but does nothing / a module-level constant reads the env before the fixture sets it / timeout_scale frozen at 1.0 / a vacuous fix that looks scaled / gh-reply-watch floor test flaked under load / two projects reported the same reply / the deferred project polled again / a wall-clock floor spanning sequential spawns / publish hangs at gate 4 validating plugin remote CPV / CPV ABORTED validate exceeded its 1800s budget / the tree is frozen for the whole publish run / I edited a file while the publish was running"
ocd: 2026-07-22
lmd: 2026-09-05
metadata:
  node_type: memory
  type: project
  tier: component
publish-globally: false
split-lineage: 08b34684a6214833bc3d78b80244d2cd
---

# janitor-publish-pipeline — gate timeouts & test-gate flakiness

^ATOM-SQZO-66VW [desc:"The pytest gate flakes under load in four distinct ways (A-D); tell them apart by the FAILURE TEXT (empty stdout / TimeoutExpired / elapsed<N / literal 'timeout'), not by which file failed.", keywords: the_test_gate_blocks_a_publish_at_random tests_fail_only_in_the_full_suite_and_pass_alone detector_exits_0_with_empty_stdout which_of_the_four_load-flake_categories_is_this assert_something_in_empty_string raw_TimeoutExpired_in_a_test the_suite_flakes_under_xdist publish_gate_red_but_tests_pass_isolated tell_the_four_flake_categories_apart_by_the_failure_text conftest_timeout-scale_knob_never_reaches_a_minimal_child_env a_production_helper_bypasses_state.run_subprocess elapsed_less_than_N_assertion_needs_a_causal_redesign the_tests_own_subprocess_run_timeout_cannot_be_scaled, ocd: 2026-08-21, lmd: 2026-08-21]

The pytest gate flakes under load in FOUR distinct ways, and each needs a DIFFERENT fix — collapsing them is why TRDD-7NSRD8OV was misdiagnosed three times before it converged.

(A) A test hand-builds a MINIMAL child env, so conftest's timeout-scale knob never reaches the spawned detector; it runs at scale 1.0, `state.run_subprocess` fails OPEN on its 10 s default, and the detector exits 0 with EMPTY stdout.
(B) A PRODUCTION helper does its own `subprocess.run` with its own ceiling, OUTSIDE `state.run_subprocess`, so scaling that seam never reaches it — `agentlens_probe.probe_json` 5 s, `cli_agent_roster.fetch_agents` 15 s, `terminal_trigger._run_aimaestro_cli` 5 s, `branch_protection_lib`'s six `gh` calls.
(C) A test asserts a WALL-CLOCK bound (`elapsed < N`). No knob fixes this, and widening the bound destroys the guard — redesign onto a causal/state assertion instead.
(D) The TEST'S OWN `subprocess.run` timeout. Nothing inside `scripts/lib` can reach a number written in a test file.

TELL THEM APART BY THE FAILURE TEXT, not by which file failed: empty stdout ⇒ A or B; a raw `TimeoutExpired` ⇒ D; an `elapsed < N` assertion ⇒ C; a literal `'timeout'` where a different classification was expected ⇒ B. [^11] [^12] [^14]




^ATOM-YPAN-OCVC [desc: "publish blocked — CPV ABORTED validate exceeded its 1800s budget, exit 124, stuck in a phase: CPV walks a nested-ignored build tree (cargo target) because it loads only the root .gitignore", keywords: CPV_ABORTED_validate_exceeded_budget exit_124_publish cpv_stuck_phase_validate_submodule_containment gitignore_filter_rglob_slow nested_.gitignore_not_honoured_by_CPV cargo_target_walked scripts/memgrep/target_huge publish_hangs_in_CPV is_dir_ignored_False_for_ignored_dir cpv-version_pin_stale, trdd: TRDD-X6I04SAO, ocd: 2026-09-02, lmd: 2026-09-02]
publish.py exited 124 with 'CPV ABORTED: validate exceeded its 1800s wall-clock budget … Phase in flight: validate_submodule_containment, stuck for 1301s' and a thread dump ending in gitignore_filter.rglob → cpv_lint_engine.detect_languages. That is not a plugin verdict; it is CPV walking a huge tree, and the 'phase in flight' name is only the batch's last START line — the thread dump names the real one. CPV's GitignoreFilter loads ONLY the root .gitignore (gitignore_filter.py:183, still so on CPV master at v5.16.0), so scripts/memgrep/target — 98,730 files / 5.1 GB, ignored only by the NESTED scripts/memgrep/.gitignore — was descended on every rglob: 32.7 s per rglob('*.py') measured with CPV's own filter, 0.2 s after adding /scripts/memgrep/target/ to the ROOT .gitignore (45d9410a). That baseline cost had been there all along (the passing 3.4.10 runs spent 297–452 s in the same batch); what tipped it over the budget on 2026-09-02 was CONCURRENT LOAD — a second session's CPV self-validation (its own .venv workers, the ones a ps grep for 'claude-plugins-validation' shows; ours runs from ~/.cache/uv/archive-v0/…/cpv-remote-validate) ran through the whole window and every phase was 1.5–13× slower. Diagnose from the thread dump, probe with GitignoreFilter(root).is_dir_ignored(<dir>), and check the machine's load before blaming the plugin; the budget cannot be raised. Upstream: claude-plugins-validation issue 226. Also noticed: .cpv-version pins v5.4.0 while CPV's latest is v5.16.0.




^rc3-with-every-test-passing-is-the-write-guard [desc: publish_blocked_but_tests_green, keywords: publish exited 3 but every test passed pytest rc=3 nothing failed write guard mutation list heartbeat wrote fleet-attribution mid-gate, type: project, ocd: 2026-07-22, lmd: 2026-07-22]
An `rc=3` from the test gate with **every test passing** is the suite's own write-guard
(`tests/conftest.py`), not a test failure — READ ITS PRINTED MUTATION LIST before believing
a leak. On a machine running the janitor for real, the guard's premise ("only the suite
writes global state") is false: the daemon ticks, other sessions fire heartbeats, and memory
agents write, all legitimately. Two consequences, both paid for:

- The guard relaxes for those SHARED-STATE labels only. **SOURCE TREE and LAUNCHD stay hard
  failures** — a test that rewrites the repo or registers an OS service is never acceptable.
- A **local heartbeat firing mid-gate** writes `fleet-attribution.json` and trips it. The
  papered workaround is to pause the beat around a publish
  (`printf x > .janitor/state/paused`, remove after). This is a SEAM, not a fix: the real fix
  is teaching the guard that sessions legitimately own some global-state files.

Building the guard's own live-actor probe failed silently THREE times (a swallowed
`ModuleNotFoundError`, then a sandboxed `HOME` that made it read the wrong home) — it now
reads the liveness file from `_REAL_ENV["HOME"]` directly. A probe that fails silently
degrades to "no other actor", i.e. it blames the suite. [^4]




^ATOM-UHO6-Q99D [desc:"gate 4 timing out has TWO causes with one symptom — a worker-pool HANG (retry) and a genuinely SLOW run (raise the cap); time a standalone run to tell them apart", keywords: publish_hangs_at_gate_4_validating_plugin_remote_CPV Command_timed_out_after_300s publish_fails_but_every_test_passed REPO_LINT_never_finishes cpv-remote-validate_stuck retry_did_not_clear_the_timeout time_a_standalone_cpv-remote-validate_run_to_tell_causes_apart worker-pool_startup_race_blocks_on_a_lock_forever BrokenProcessPool_never_raised_when_workers_fail_to_spawn the_discriminator_is_completion_not_duration a_genuine_hang_now_takes_900s_to_catch _CPV_TIMEOUT_SEC_replaced_three_unstated_numbers, type: project, ocd: 2026-07-28, lmd: 2026-07-30]

Gate 4 (`stage_validate`, remote CPV) times out for **two different reasons that print the same
line**, and the remedies are opposites. Decide which one you have BEFORE acting, with one cheap
measurement: run `cpv-remote-validate plugin . --strict` standalone under `time`.

**(a) It COMPLETES (~237s measured 2026-07-30, EXIT=0).** The run is merely slow and the cap was too
tight: `stage_validate` passed no `timeout=`, inheriting `run()`'s generic 300s — under 27% headroom,
so it passed idle and failed under load. Retrying does NOT help; it failed twice and cleared only
when the cap rose. Since `a168149` all three CPV call sites read `_CPV_TIMEOUT_SEC` (900s) — before
it they used 600/300/none, one behaviour with three unstated numbers.

**(b) It NEVER completes.** Then it is the worker-pool startup RACE: CPV's `[REPO LINT]` fans out a
pool, and when the ~15 workers fail to spawn the parent blocks on a lock forever instead of raising
`BrokenProcessPool`. Intermittent, so RETRY works — there is no `--jobs`/serial flag.
`/usr/bin/sample <pid> 4` confirms it: main thread pinned in
`lock_PyThread_acquire_lock -> acquire_timed -> __psynch_cvwait`, threads in
`_queue_SimpleQueue_get`, `ps` showing a `multiprocessing.resource_tracker` child with ZERO workers.

The discriminator is COMPLETION, not duration — a hang never finishes, so a standalone EXIT=0 rules
(b) out. Accepted trade-off: a genuine hang now takes 900s to catch, the price of making (a)
satisfiable at all. [^5] [^7] [^10]




^ATOM-0GXI-QA1C [desc:"the tree is frozen for the whole publish — an edit mid-run fails it and the message blames the tests", keywords: publish_exited_3_but_every_test_passed REAL-STATE_WRITE_GUARD_FAILED a_test_escaped_isolation_but_no_test_failed working_tree_is_dirty_commit_or_stash_first publish_keeps_failing_while_I_edit the_tree_is_frozen_for_the_whole_publish_run editing_a_source_file_mid-publish_kills_the_gate source-tree_changed_line_names_the_exact_path plugin-data_changed_line_is_tolerated_as_the_live_daemon commit_everything_before_starting_a_publish keep_hands_off_the_tree_until_exit_is_printed cost_two_publish_runs_before_this_was_understood, type: project, ocd: 2026-07-28, lmd: 2026-07-28]

The publish pipeline treats the working tree as FROZEN for its whole run, and enforces that in two
places: gate 1 refuses a dirty tree, and the test gate's REAL-STATE WRITE GUARD fails the run (rc=3,
with every test passing) if any guarded path changed while pytest was executing. Editing a source file
during the ~12 minutes a publish takes therefore kills it — and the guard reports it as
"a test escaped isolation", which points at the suite rather than at the actual writer. It names the
exact path, so read that first: `[source-tree] CHANGED: <file>` is almost always an editor, not a test.
A `[plugin-data] CHANGED:` line is tolerated separately ("attributed to the LIVE daemon"). Cost two
runs on 2026-07-28: once at gate 1 (uncommitted memory pages) and once at gate 3 (a docstring edited
mid-run). Commit everything first, then start the publish, then keep hands off until EXIT is printed. [^6]

Pairs with `^rc3-with-every-test-passing-is-the-write-guard`, which describes the SAME rc=3 signature
from a different writer — the heartbeat/daemon mutating state mid-gate rather than an agent editing
source. Both surface on the same symptom query, and that is intended: read the guard's `[source-tree]`
vs `[plugin-data]` prefix to tell which one you are looking at. [^8]



## Governed by

- [[janitor-publish-pipeline]] — the publish-pipeline overview hub this page details.

## See also

- `[[debugging-methodology]]` (USER scope) — owns the GENERAL method behind
  `^ATOM-UHO6-Q99D`: separating a SLOW operation from a STUCK one before touching any
  timeout (`^ATOM-KYV1-HR97` + its lesson). This page keeps only the CPV-specific facts;
  the transferable technique belongs there, so it is findable from a hang that has
  nothing to do with publishing.

## Notes and lessons learned
[^4]: [id:ATOM-MG22-0002, status:valid, keywords:"guard_assumes_it_is_the_only_writer live_daemon_and_sessions_write_too silent_probe_failure_blames_the_suite", ocd:2026-07-22, lmd:2026-07-22]
  DO NOT write a "did the suite touch anything outside its boundary" guard that assumes the
  suite is the only writer, BECAUSE on a machine actually running the product the daemon,
  other sessions and background agents write that same state legitimately — the guard then
  blocks publishes with every test green. DO detect other live actors first, and make that
  probe fail LOUDLY: mine failed silently three times and each failure degraded to "no other
  actor", i.e. it blamed the suite.
[^5]: [id:ATOM-RHYL-686X, status:valid, desc:"the cap was doing its job — measure the hang before touching the number", keywords:"raise_the_timeout_because_it_timed_out timeout_is_indistinguishable_from_a_hang sample_the_stuck_process_before_changing_the_cap cpu_time_flatlined_means_hang_not_slow", ocd:2026-07-28, lmd:2026-07-28] DO NOT raise a gate timeout because the gate timed out, BECAUSE a timeout is indistinguishable from a hang until you look, and the cap is often the only thing converting an unbounded hang into a bounded failure — raising it turns a 5-minute red into a wedged release. DO sample the stuck process first (`/usr/bin/sample <pid> 4`, `ps` for CPU-time growth, `lsof -a -i` for a socket) and let the stack name the cause.
[^6]: [id:ATOM-BTNN-2OX0, status:valid, desc:"the publish freezes the tree; my own edit failed two runs and the message pointed at the suite", keywords:"edited_a_file_while_the_publish_was_running write_guard_blamed_the_tests_but_it_was_me tree_is_frozen_for_the_whole_publish commit_before_publishing_then_hands_off", ocd:2026-07-28, lmd:2026-07-28] DO NOT edit the working tree while a publish is running, BECAUSE the pipeline froze that tree at gate 1 and re-validates it at the test gate and again at the commit gate — so an edit twelve minutes in fails the run, and the write guard blames "a test escaped isolation" rather than the editor, which sends you hunting through a suite that is fine. DO commit everything first, start the publish, and keep hands off until EXIT prints.
[^7]: [id:ATOM-4TQF-J8ND, status:valid, desc:"one symptom, two opposite remedies — a prescription that names only one cause sends the next reader in circles", keywords:"retry_the_publish_did_not_help timed_out_again_after_retrying same_error_two_different_causes memory_said_retry_but_retry_failed cap_too_tight_vs_genuine_hang", ocd:2026-07-30, lmd:2026-07-30] DO NOT record "symptom X means cause Y, do Z" when a second cause prints the identical line, BECAUSE the next reader applies Z, watches it fail, and has no way to tell a wrong diagnosis from bad luck — `^ATOM-UHO6-Q99D` said gate 4's timeout is "not a too-tight cap, retry, do not raise it", so I retried twice into a cap that was genuinely 27% over the real runtime. DO write the DISCRIMINATOR beside the causes (here: time a standalone run — a hang never completes, a slow run returns EXIT=0), so the reader tests rather than guesses.
[^8]: [id:ATOM-WKVX-G7S6, status:valid, desc:"since v2.7.0 the freeze is ENFORCED by a PreToolUse hook, not just documented", keywords:"my_edit_was_denied_by_publish-lock PreToolUse_hook_blocked_my_Edit_during_a_release A_publish.py_release_is_running_on_this_repo_right_now publish-in-progress.json why_can_I_not_edit_this_file_right_now edit_denied_while_publishing is_the_publish_lock_stale publish_crashed_and_left_a_lock_file", ocd:2026-08-07, lmd:2026-08-07] DO NOT rely on remembering the tree-freeze — as of v2.7.0 it is ENFORCED, BECAUSE documenting it was not enough: this atom already recorded the 2026-07-28 double failure and the identical pair happened again on 2026-08-07 (gate 3 twice), the second time after the risk was named out loud and taken anyway. `publish.py` now writes `.janitor/state/publish-in-progress.json` (pid + start, gitignored) and `scripts/hooks/pre-tool-publish-lock.py` DENIES Edit/Write/MultiEdit/NotebookEdit against a repo holding a live lock. DO read the deny text as information, not an obstacle — it means a release is mid-run; wait for EXIT. It fails OPEN on a dead pid, a stale lock (>1h, `CLAUDE_PLUGIN_OPTION_PUBLISH_LOCK_MAX_AGE_S`), a malformed file, or another repo's path, so a crashed publish can never wedge editing; delete the file if you ever need to force it. The guard covers the editing TOOLS only — a `Bash` write still slips through.
[^10]: [id: ATOM-CYCK-6DTW, status: valid, desc: "the THIRD cause of a gate timeout — host saturation — and the reading that separates it from a hang and from a tight cap", keywords: "publish_gate_timed_out_but_the_test_passes_alone TimeoutExpired_on_an_xdist_worker_gw3_gw11 should_I_raise_the_publish_test_timeout is_this_flaky_or_a_real_regression retry_the_publish_or_fix_the_cap load_average_was_70_when_the_gate_failed subprocess_timeout_under_parallel_test_fanout", ocd: 2026-08-16, lmd: 2026-08-16] DO NOT choose between "it hung" and "the cap is too tight" when a publish gate times out, BECAUSE a THIRD cause exists that both prior discriminators mis-read — HOST SATURATION — and it is the only one whose correct action is to change nothing and retry. MEASURED 2026-08-16: gate 4 died on `TimeoutExpired` for two unrelated tests on xdist workers `gw3`/`gw11` (30 s and 60 s caps); run standalone they passed together in **6.22 s**, i.e. 5x UNDER the smaller cap, so lesson [7]'s "a slow run returns EXIT=0" reported neither a hang nor a tight cap; `uptime` at that moment read **load average 43.8 / 70.7** with `fseventsd` at 77% and 1119 processes. An unchanged retry passed the same two tests. DO read the LOAD AVERAGE alongside the standalone timing: standalone-fast AND load high ⇒ saturation, retry unchanged; standalone-slow-but-completing ⇒ the cap really is tight (lesson [7]); standalone-never-completes ⇒ a hang, sample it (lesson [5]). And check for ORPHANED workers first (`ps` to a FILE, then grep the file) — zero here, so the load was the machine's own, not a leaked fanout of mine, which is the one case where retrying just reproduces the failure.
[^11]: [id: ATOM-HM5W-LQ1R, status: valid, desc: "the FIX shape for category D — a seam, never an enumeration", keywords: "how_do_I_fix_category_D_load_flake tests_own_subprocess_timeout_under_load should_I_scale_every_timeout_call_site enumerating_call_sites_keeps_missing_some TimeoutExpired_in_a_test_under_xdist scale_timeouts_at_a_seam_not_per_site", ocd: 2026-08-21, lmd: 2026-08-21] DO NOT fix a category-D load flake by hand-scaling the test files' own `timeout=` literals, BECAUSE there are ~258 of them in `tests/` and three separate enumerations each came back too narrow — each pass looked complete and the next soak named files the pass had missed. DO scale at the one layer they all funnel through: wrap `Popen.communicate` and `Popen.wait` in an autouse conftest fixture (`conftest.scale_timeout_kwarg`), which covers every present AND future site once. Do NOT also wrap `subprocess.run` — it forwards its own timeout down to `communicate`, so patching both double-scales.
[^12]: [id: ATOM-8KPE-FJGU, status: valid, desc: "the vacuous-constant trap when scaling timeouts", keywords: "my_timeout_scaling_looks_applied_but_does_nothing module_level_constant_reads_env_before_the_fixture_sets_it timeout_scale_frozen_at_1.0 the_fix_is_there_and_the_flake_still_happens vacuous_fix_that_looks_scaled", ocd: 2026-08-21, lmd: 2026-08-21] DO NOT compute a scaled timeout into a MODULE-LEVEL constant (`_T30 = 30 * state.timeout_scale()`), BECAUSE module import runs at COLLECTION time, before pytest's autouse fixtures set the env the scale reads — so the scale freezes at 1.0, the constant keeps its unscaled value, and the site looks fixed while behaving exactly as before. DO read the scale at CALL time, or scale at a runtime seam; a soak that still names a "fixed" file is the symptom.
[^14]: [id: ATOM-SOYF-156O, status: valid, desc: "gh-reply-watch floor test flaked under load: the stamp's window spans the first child's whole run", keywords: "expected_the_first-come_token_to_starve_all_but_one_project deferred_project_polled_again gh-reply-watch_floor_test_flakes_under_load machine-wide_poll_floor_expired_mid-test wall-clock_floor_spanning_sequential_spawns second_projects_fire_was_not_deferred test_without_the_inbox_only_ONE_project_on_a_host_sees_the_reply test_gh_reply_watch.py_failed_only_in_the_publish_gate gh-reply-watch-global-poll.last-run.ts_stamp janitor#215_floor_test_flaky is_the_60_s_poll_floor_broken two_projects_reported_the_same_reply _GLOBAL_MIN_INTERVAL_S_window_elapsed_during_the_test publish_blocked_by_test_gh_reply_watch", ocd: 2026-09-02, lmd: 2026-09-02] DO NOT read the gh-reply-watch floor tests failing with 'expected the first-come token to starve all but one project, 2 reported' (or a second project's fire not deferred) as a gate bug, BECAUSE the machine-wide stamp carries the FIRST child's start-time now, so a sequential later child's 60 s window has been running for the first child's WHOLE run — under xdist load the gap from the first child's start to the second's reached the 60 s floor — inferred from `2 reported`, not timed — and the floor expired mid-test (2026-09-02 publish gate): category C, a wall-clock bound hidden in the fixture, not a fifth category. DO re-stamp the floor to NOW right before each later fire (tests/test_gh_reply_watch.py::_re_arm_floor — the mirror of the expiry test's back-dating), AFTER asserting the detector's stamp is >= the test's clock reading taken before the first fire — without that value check a `_mark_global_poll` writing `0` stays green (mutation-probed RED 2026-09-02); this keeps the claim causal and shrinks the timing assumption to one child's start-up.
