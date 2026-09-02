---
name: janitor-publish-pipeline
description: "publish blocked / how do I release the janitor / CPV flagged a finding / can I skip a gate / push rejected by pre-push hook / version mismatch on publish / no changelog / publish exited 3 but every test passed / rc=3 with nothing failing / the gate timed out but the test passes on its own / TimeoutExpired on an xdist worker / is this flaky or a real regression — the janitor's fail-fast publish pipeline (a CPV plugin), its gate order, the write-guard, and the CPV-only validate policy / the test gate blocks a publish at random / tests fail only in the full suite and pass alone / a detector exits 0 with empty stdout / assert something in an empty string / which load-flake category is this / should I scale every timeout call site or enumerate them / enumerating call sites keeps missing some / scale timeouts at a seam not per site / my timeout scaling looks applied but does nothing / a module-level constant reads the env before the fixture sets it / timeout_scale frozen at 1.0 / a vacuous fix that looks scaled / gh-reply-watch floor test flaked under load / two projects reported the same reply / the deferred project polled again / a wall-clock floor spanning sequential spawns"
ocd: 2026-06-13
lmd: 2026-09-02
metadata:
  node_type: memory
  type: project
  tier: component
  globs:
    - "scripts/publish.py"
    - "cliff.toml"
    - "CHANGELOG.md"
publish-globally: false
---

The janitor ships via `scripts/publish.py` — a strict, **fail-fast** release
pipeline. **It is a CPV plugin**, so its pipeline includes the CPV plugin-schema +
security gate. Not every fleet project is a plugin: **non-plugin agents (e.g.
service-style or library projects) have their OWN pipelines** — this page
documents the janitor's specifically; do not assume another project releases the
same way. The pipeline auto-detects the project (it is language-agnostic:
claude-plugin / python / rust / go / node / bash can coexist) and runs an
ordered set of gates; **any gate failing exits non-zero and the release stops**
— there is no skip, no force, no bypass.

**Gate sequence (in order; each is mandatory; failure = stop):**

1. **Self-integrity + env-bypass rejection** — before anything runs, `main()`
   greps its OWN source for forbidden bypass patterns (`--skip-tests`,
   `--skip-lint`, `--skip-validate`, `--no-validate`, `--force-publish`,
   `--bypass`, `skip_*` variables) and refuses to run if any appear outside the
   two authorized allowlists. It then rejects a set of bypass env vars
   (`SKIP_TESTS`, `SKIP_VALIDATE`, `CPV_SKIP`, `CPV_NO_STRICT`, `FORCE_PUBLISH`,
   `BYPASS_VALIDATION`, …). This makes the no-skip policy self-enforcing against
   future edits.
2. **Step 0 — auto-detect** git root, plugin root (walks up to
   `.claude-plugin/plugin.json`), plugin info, marketplace (from git remote),
   default branch, and whether the plugin lives in a subfolder.
3. **Step 0.5 — install/refresh the pre-push hook** (the strict gate; see the
   push-guard model below). Regenerated from an inline template on every run so
   a locally-edited hook can't survive as a bypass. This is the ONE intentional
   side effect of `--dry-run`.
4. **Step 1 — clean working tree** (`git status --porcelain`); a `uv.lock`-only
   dirty tree is auto-committed (skipped under `--dry-run`), anything else
   aborts.
5. **Step 2 — language-native TESTS** (mandatory, per detected language; any
   failure exits). A no-op only if no test infra exists for any detected
   ecosystem.
6. **Step 3 — language-native LINT** (mandatory, zero errors): ruff (Python),
   clippy (Rust), go vet, the `lint` npm script (Node), shellcheck (bash), plus
   the by-extension linters (pymarkdown, yamllint, json, toml).
7. **Step 4 — CPV `--strict` VALIDATE** (only when the project is a claude
   plugin): `uvx --from git+<CPV repo> cpv-remote-validate plugin <plugin-root>
   --strict`. This is the SOLE validation invocation — it covers the full plugin
   schema check + the strict rule set.[^2] (Historical: a separate `cpv … lint` step
   existed; CPV ≥ v2.71.0 retired it after fixing its gitignore-walk bug, so the
   single `plugin --strict` pass now covers everything.)
8. **Step 6 — version consistency** across plugin.json / pyproject.toml /
   package.json / Cargo.toml / Python `__version__`; a mismatch aborts. [^1]
9. **Step 7 — git-cliff availability pre-check** (fail BEFORE any file mutation —
   every release MUST produce a CHANGELOG entry + release notes).
10. **Step 8 — compute the bumped semver** from `--major | --minor | --patch`
    (exactly one is required).
11. **Step 9 — bump the version** in every applicable config file (and re-`uv
    lock` so the lockfile tracks the new version).
12. **Step 10 — git-cliff CHANGELOG + release notes**: `git cliff --bump
    --unreleased --tag vX.Y.Z -o CHANGELOG.md`, extracting the notes for the
    GitHub release into a gitignored `.git-cliff-release-notes.md`.
13. **Step 11 — commit** the bump + CHANGELOG (stages only known-modified files
    by name — NEVER `git add -A`, which could pick up secrets or scratch).
14. **Step 12 — annotated tag** `vX.Y.Z` whose body is the extracted release
    notes, PLUS the bare **resolver twin tag** `<plugin-name>--vX.Y.Z` — Claude
    Code ≥ 2.1.110 dependents resolve `dependencies` version constraints ONLY
    against `{name}--v{version}` tags, so a release without the twin tag breaks
    every dependent's constrained install (#85/#90; shipped v0.45.0). The
    resolution mechanics live on the USER-scope `claude-plugin-dependencies`
    page.[^3]
15. **Step 13 — push** commit + BOTH tags to `origin/<default-branch>`.
16. **Step 14 — create the GitHub release** (mandatory; `gh release create` with
    `--notes-file`) so Claude Code's plugin-update detector sees the new version.
    Missing/unauthenticated `gh` fails the pipeline (no silent skip).

`--dry-run` runs every validation gate fully, then stops before the bump/commit/
push (it mutates nothing in git history; its only side effect is installing the
push-guard hook).

**CPV-ONLY validation policy + devitalize-or-remove (PRRD S5.1):** the pipeline
invokes ONLY the CPV plugin for validation — there are NO local copies of any
validator script. A CPV finding is cleared by **devitalizing or removing** the
offending code, **NEVER** by exempting/suppressing a rule or relaxing `--strict`.
The exempt-list mechanism was dropped fleet-wide as trivially exploitable.
Concretely: an execution-class security finding (live `os.system` /
`subprocess(shell=True)`, pipe-to-shell install docs, `eval`/`exec` of a string,
backtick command substitution, hardcoded tokens in docs, raw detection-pattern
signatures) is rewritten into provably-inert data the scanner recognizes
(see the CPV `devitalize-threats` catalog) — you make the code's executable
shape inert, you do not silence the rule.

**Admin-bypass-for-publish.py branch-ruleset model:** the default branch carries
the ratified baseline ruleset pair (history-protect: no force-push / no deletion
with NO bypass actor;[^9] pr-and-checks: PR ≥ 1 approval + required
status checks, with an admin direct-push bypass). The admin bypass exists
precisely so `publish.py` can push the release commit + tag directly to the
default branch while ordinary contributions still go through PRs. Two layers
guard this: (a) the GitHub ruleset's admin bypass, and (b) a local **pre-push
hook** that verifies its caller by **process ancestry** — it walks the PID tree
looking for a `python … scripts/publish.py` ancestor and only then allows the
push. No env var is involved (process trees can't be spoofed), so a stray
`git push` from outside the pipeline is refused locally even before GitHub.

Run forms: `scripts/publish.py --patch` (or `--minor` / `--major`), add
`--dry-run` to exercise every gate without releasing.

**Machine-specific facts live in LOCAL scope** (named here, not stored): the
absolute repo-root path, the owner GitHub identity / `gh` auth, account emails,
and any OAuth tokens. This page is git-tracked and host-global, so it carries
only generic procedure (use `<repo-root>`, `$HOME`, `<email>`, the CPV repo by
name, never literal paths or secrets).


^ATOM-SQZO-66VW [keywords: the_test_gate_blocks_a_publish_at_random tests_fail_only_in_the_full_suite_and_pass_alone detector_exits_0_with_empty_stdout which_of_the_four_load-flake_categories_is_this assert_something_in_empty_string raw_TimeoutExpired_in_a_test the_suite_flakes_under_xdist publish_gate_red_but_tests_pass_isolated tell_the_four_flake_categories_apart_by_the_failure_text conftest_timeout-scale_knob_never_reaches_a_minimal_child_env a_production_helper_bypasses_state.run_subprocess elapsed_less_than_N_assertion_needs_a_causal_redesign the_tests_own_subprocess_run_timeout_cannot_be_scaled, ocd: 2026-08-21, lmd: 2026-08-21]

The pytest gate flakes under load in FOUR distinct ways, and each needs a DIFFERENT fix — collapsing them is why TRDD-7NSRD8OV was misdiagnosed three times before it converged.

(A) A test hand-builds a MINIMAL child env, so conftest's timeout-scale knob never reaches the spawned detector; it runs at scale 1.0, `state.run_subprocess` fails OPEN on its 10 s default, and the detector exits 0 with EMPTY stdout.
(B) A PRODUCTION helper does its own `subprocess.run` with its own ceiling, OUTSIDE `state.run_subprocess`, so scaling that seam never reaches it — `agentlens_probe.probe_json` 5 s, `cli_agent_roster.fetch_agents` 15 s, `terminal_trigger._run_aimaestro_cli` 5 s, `branch_protection_lib`'s six `gh` calls.
(C) A test asserts a WALL-CLOCK bound (`elapsed < N`). No knob fixes this, and widening the bound destroys the guard — redesign onto a causal/state assertion instead.
(D) The TEST'S OWN `subprocess.run` timeout. Nothing inside `scripts/lib` can reach a number written in a test file.

TELL THEM APART BY THE FAILURE TEXT, not by which file failed: empty stdout ⇒ A or B; a raw `TimeoutExpired` ⇒ D; an `elapsed < N` assertion ⇒ C; a literal `'timeout'` where a different classification was expected ⇒ B. [^11] [^12] [^14]


^ATOM-M8YK-YILO [desc: "publish.py [G1b] blocks a push whose ADDED lines introduce a non-allow-listed e-mail address the same file did not already hold on the remote base ref; masked output; the gate scans its own tests", keywords: personal_e-mail_address_introduced G1b_personal-address_lint BLOCKED_personal_e-mail_address publish_blocked_on_an_email_address gmail_address_in_a_tracked_file redact_the_way_the_repo_already_does address_already_on_the_base_ref masked_address_f***@domain users.noreply.github.com_allowed example.com_allowed per-file_known_address_exclusion git_show_ref_path added_lines_only the_gate_flagged_its_own_test_file, type: project, trdd: TRDD-QW7K3M2V, ocd: 2026-09-02, lmd: 2026-09-02]

`scripts/publish.py` gate `[G1b] Personal-address lint` (2026-09-02, TRDD-QW7K3M2V, commits da471290/fb48d144/92af2072): after [G1] it diffs `<remote default ref>...HEAD` with `--unified=0` and scans ADDED lines only for an e-mail address whose domain is not allow-listed (`users.noreply.github.com`, RFC reserved doc domains .local/.test/.example/.invalid/.localhost, exact example.com/org/net, local parts noreply/no-reply) and that the SAME FILE did not already hold on the base ref (`git show <ref>:<path>`, per file — a repo-wide set would let an address living only in a frozen terminal card be pasted into any new file). A hit blocks the push and prints the address MASKED (`f***@domain`). It exists because three personal addresses already sit in 12 tracked files of this public repo since 2026-05-28 and the owner ruled: leave history alone, stop the bleeding (option 1). The gate's own test module must assemble every flaggable address at runtime around a split `@` and never spell one in a comment — the gate scans its own tests too. [^13]

## See also

- `[[project_janitor_publish_blocked_cpv_fps]]` — the publish-gate history + the
  devitalize-or-remove unblock recipe (RESOLVED; v0.7.x shipped).
- [[janitor-self-update-bootstrap-gap]] — the OTHER half of a release: after publish.py
  succeeds, why the local cache can stay on the old version (the fast-updater can't
  accelerate its own first release; reload ≠ update).
- `[[debugging-methodology]]` (USER scope) — owns the GENERAL method behind
  `^ATOM-UHO6-Q99D`: separating a SLOW operation from a STUCK one before touching any
  timeout (`^ATOM-KYV1-HR97` + its lesson). This page keeps only the CPV-specific facts;
  the transferable technique belongs there, so it is findable from a hang that has
  nothing to do with publishing.

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


^ATOM-FGXY-NBTB [desc:"CPV's pin is written LITERALLY in both workflows and kept equal to .cpv-version by a test — an SSOT indirection there is a MAJOR that blocks the publish", keywords: publish_blocked_by_a_MAJOR_about_a_non-resolvable_CPV_ref workflow_pins_a_non-resolvable_ref can_I_read_the_CPV_version_from_a_file_at_runtime where_is_the_CPV_tag_pinned bumping_the_CPV_version the_cpv_tag_is_written_literally_in_both_workflows test_cpv_pin_ssot.py_gate_fails_until_they_match edit_.cpv-version_then_update_every_workflow_call_site drift_cannot_reach_the_remote_because_of_the_ssot_test publish_blocked_by_a_MAJOR_cpv_ref_severity ci.yml_and_release.yml_both_pin_the_cpv_tag no_runtime_indirection_for_the_cpv_version, type: project, ocd: 2026-08-01, lmd: 2026-08-01]

**The CPV tag is written LITERALLY in both workflows** (`ci.yml` once, `release.yml` twice)
and kept equal to `.cpv-version` by `tests/test_cpv_pin_ssot.py`, which `publish.py` runs as
a gate — so drift cannot reach the remote. To bump: edit `.cpv-version`, then update every
workflow call site in the same commit; the test names them and fails until they match.

Do NOT "DRY" this by reading the file into a shell var and interpolating `@${VAR}`. CPV's
validator inspects the workflow YAML **statically** and cannot evaluate a shell variable, so
it reads the ref as non-resolvable and raises one MAJOR per call site — 3 findings, publish
blocked (measured 2026-08-01, on a construction that bash would in fact have expanded
correctly). The literal is also the auditable form: a reviewer sees which CPV version CI
executes without tracing a file read, which is the same property the surrounding comment
demands when it refuses an UNPINNED resolve.

The general shape, worth carrying elsewhere: an SSOT indirection is only free when every
CONSUMER can follow it. A consumer that reads your file as text rather than running it sees
the indirection, not the value — so the fix is not to abandon the SSOT but to move the
enforcement into a test, where duplication becomes checked rather than trusted.

## Notes and lessons learned
[^1]: [id:ATOM-MG06-0011, status:valid, keywords:"pipeline_step_numbers_skip_preserve renumbering_breaks_log_greps removed_stage_keep_downstream_numbers", ocd:2026-06-13, lmd:2026-06-13] The step numbers intentionally skip 5 —
  the old "Step 5: CPV lint" was folded into the single Step 4 `plugin --strict`
  pass when CPV retired its `lint` subcommand, but the later step numbers were
  kept on their original sequence (Step 6 follows Step 4) so log greps against
  any existing release-history line still hit. Lesson: when removing a pipeline
  stage, preserve downstream step numbering if logs are grepped by it, rather
  than renumbering and breaking historical log queries.
[^2]: [id:ATOM-MG06-0012, status:valid, keywords:"cpv_strict_lints_trdd_markdown wrapped_continuation_plus_marker_nit trailing_echo_masks_publish_exit", ocd:2026-06-25, lmd:2026-06-25] Step-4 CPV `--strict` runs a markdownlint
  that scans MORE files than Step-3's own pymarkdown — notably `design/tasks/*.md`
  (the TRDDs), which Step 3 does NOT scan. So a markdown formatting bug in a TRDD
  passes the local lint and only fails at the CPV gate (v0.24.6 hit this). The trap
  (issue #113): a hard-wrapped prose line beginning `+ ` (or `* `) is read by
  markdownlint MD004/ul-style as a rogue `+`-marker list item, "mixing" it with the
  file's `-` bullets → a blocking NIT. Lesson: never start a wrapped markdown
  continuation with `+ `/`* `/`- `. Companion gotcha, same incident: a background
  `publish.py > LOG; echo "EXIT=$?"` wrapper reports exit 0 (the echo's status, not
  publish.py's), MASKING a validate failure — drop the trailing echo, and ALWAYS
  recheck version+branch after a "successful" publish (a failed validate bumps
  nothing and pushes nothing).
[^3]: [id:ATOM-MG06-0013, status:valid, keywords:"skill_body_5000_bpe_cap rules_corpus_52000_byte_cap size_gate_displace_bytes", ocd:2026-07-16, lmd:2026-07-16] Three v0.45.0 release lessons. (a) TWO SIZE
  gates exist and both bit: CPV `--strict` caps each SKILL.md body at **5000 BPE
  tokens** (janitor-memory-write ~5538 and consolidate ~5095 blocked as MAJORs
  after feature additions; fix = compress the body, push detail into
  `references/` — it took TWO shave rounds, the first left write at 5007); and
  the repo's own `test_shipped_rules_stay_under_the_context_floor_cap` caps the
  shipped `rules/*.md` corpus at **52000 bytes** and sat at ZERO headroom, so
  any rule addition must DISPLACE an equal number of bytes from the corpus. (b)
  I committed a "fix" (99a611e) the gate still rejected — run the failing gate
  BEFORE the commit that claims to fix it, not after. (c) The resolver twin tag
  was MISSING from every pre-0.45.0 release; publish.py Step 12/13 now emits it
  automatically (7b47f7c) — never hand-tag it, the pipeline owns it.
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
[^9]: [id:ATOM-QFXP-33LD, status:valid, desc:"required_linear_history was REMOVED from baseline-history-protect by Tier-3 ruling — do not describe or re-add it", keywords:"baseline-history-protect linear_history required_linear_history ratified_baseline branch_ruleset_payload does_history-protect_require_linear_history hand-built_ruleset_payload_reapplied_linear_history", ocd:2026-08-08, lmd:2026-08-08] DO NOT describe `required_linear_history` as part of `baseline-history-protect` or re-add it, BECAUSE the USER removed it by Tier-3 ruling 2026-08-08 (janitor#14; Emasoft/ai-maestro daec2d69) after it proved unfollowable — the code SSOT (`scripts/lib/branch_protection_lib.py`) had already dropped it, and a hand-built payload from stale rule PROSE re-applied it fleet-wide for half a day. DO build baseline payloads from `branch_protection_lib.baseline_ruleset_payloads`, never from governance prose.
[^10]: [id: ATOM-CYCK-6DTW, status: valid, desc: "the THIRD cause of a gate timeout — host saturation — and the reading that separates it from a hang and from a tight cap", keywords: "publish_gate_timed_out_but_the_test_passes_alone TimeoutExpired_on_an_xdist_worker_gw3_gw11 should_I_raise_the_publish_test_timeout is_this_flaky_or_a_real_regression retry_the_publish_or_fix_the_cap load_average_was_70_when_the_gate_failed subprocess_timeout_under_parallel_test_fanout", ocd: 2026-08-16, lmd: 2026-08-16] DO NOT choose between "it hung" and "the cap is too tight" when a publish gate times out, BECAUSE a THIRD cause exists that both prior discriminators mis-read — HOST SATURATION — and it is the only one whose correct action is to change nothing and retry. MEASURED 2026-08-16: gate 4 died on `TimeoutExpired` for two unrelated tests on xdist workers `gw3`/`gw11` (30 s and 60 s caps); run standalone they passed together in **6.22 s**, i.e. 5x UNDER the smaller cap, so lesson [7]'s "a slow run returns EXIT=0" reported neither a hang nor a tight cap; `uptime` at that moment read **load average 43.8 / 70.7** with `fseventsd` at 77% and 1119 processes. An unchanged retry passed the same two tests. DO read the LOAD AVERAGE alongside the standalone timing: standalone-fast AND load high ⇒ saturation, retry unchanged; standalone-slow-but-completing ⇒ the cap really is tight (lesson [7]); standalone-never-completes ⇒ a hang, sample it (lesson [5]). And check for ORPHANED workers first (`ps` to a FILE, then grep the file) — zero here, so the load was the machine's own, not a leaked fanout of mine, which is the one case where retrying just reproduces the failure.
[^11]: [id: ATOM-HM5W-LQ1R, status: valid, desc: "the FIX shape for category D — a seam, never an enumeration", keywords: "how_do_I_fix_category_D_load_flake tests_own_subprocess_timeout_under_load should_I_scale_every_timeout_call_site enumerating_call_sites_keeps_missing_some TimeoutExpired_in_a_test_under_xdist scale_timeouts_at_a_seam_not_per_site", ocd: 2026-08-21, lmd: 2026-08-21] DO NOT fix a category-D load flake by hand-scaling the test files' own `timeout=` literals, BECAUSE there are ~258 of them in `tests/` and three separate enumerations each came back too narrow — each pass looked complete and the next soak named files the pass had missed. DO scale at the one layer they all funnel through: wrap `Popen.communicate` and `Popen.wait` in an autouse conftest fixture (`conftest.scale_timeout_kwarg`), which covers every present AND future site once. Do NOT also wrap `subprocess.run` — it forwards its own timeout down to `communicate`, so patching both double-scales.
[^12]: [id: ATOM-8KPE-FJGU, status: valid, desc: "the vacuous-constant trap when scaling timeouts", keywords: "my_timeout_scaling_looks_applied_but_does_nothing module_level_constant_reads_env_before_the_fixture_sets_it timeout_scale_frozen_at_1.0 the_fix_is_there_and_the_flake_still_happens vacuous_fix_that_looks_scaled", ocd: 2026-08-21, lmd: 2026-08-21] DO NOT compute a scaled timeout into a MODULE-LEVEL constant (`_T30 = 30 * state.timeout_scale()`), BECAUSE module import runs at COLLECTION time, before pytest's autouse fixtures set the env the scale reads — so the scale freezes at 1.0, the constant keeps its unscaled value, and the site looks fixed while behaving exactly as before. DO read the scale at CALL time, or scale at a runtime seam; a soak that still names a "fixed" file is the symptom.
[^13]: [id: ATOM-W9LC-3G7E, status: valid, desc: "A repo-scanning lint must be run over its own commit before landing; fixtures and comments are tracked lines too", keywords: "the_gate_flagged_its_own_test_file lint_blocked_the_commit_that_ships_the_lint test_fixture_contains_a_real-looking_email literal_gmail_address_in_tests self-tripping_gate split_the_at_sign_in_fixtures run_the_lint_over_origin/main_before_committing G1b_hits_in_tests/test_publish_personal_address_gate.py comment_spelled_out_an_address address_regex_matches_source_code", ocd: 2026-09-02, lmd: 2026-09-02] DO NOT write a flaggable literal (a gmail-style address) into the address gate's own tests or comments, BECAUSE [G1b] scans every ADDED line of every tracked file including its own test module — measured 2026-09-02: six hits from literal fixtures, then one more from a comment that spelled an address out, each would have blocked the publish shipping the gate. DO assemble every flaggable fixture at runtime around a split '@' (`f"{local}{AT}gmail.com"`) and run the two helpers over origin/main...HEAD before committing any lint that scans the repo.
[^14]: [id: ATOM-SOYF-156O, status: valid, desc: "gh-reply-watch floor test flaked under load: the stamp's window spans the first child's whole run", keywords: "expected_the_first-come_token_to_starve_all_but_one_project deferred_project_polled_again gh-reply-watch_floor_test_flakes_under_load machine-wide_poll_floor_expired_mid-test wall-clock_floor_spanning_sequential_spawns second_projects_fire_was_not_deferred test_without_the_inbox_only_ONE_project_on_a_host_sees_the_reply test_gh_reply_watch.py_failed_only_in_the_publish_gate gh-reply-watch-global-poll.last-run.ts_stamp janitor#215_floor_test_flaky is_the_60_s_poll_floor_broken two_projects_reported_the_same_reply _GLOBAL_MIN_INTERVAL_S_window_elapsed_during_the_test publish_blocked_by_test_gh_reply_watch", ocd: 2026-09-02, lmd: 2026-09-02] DO NOT read the gh-reply-watch floor tests failing with 'expected the first-come token to starve all but one project, 2 reported' (or a second project's fire not deferred) as a gate bug, BECAUSE the machine-wide stamp carries the FIRST child's start-time now, so a sequential later child's 60 s window has been running for the first child's WHOLE run — under xdist load the gap from the first child's start to the second's reached the 60 s floor — inferred from `2 reported`, not timed — and the floor expired mid-test (2026-09-02 publish gate): category C, a wall-clock bound hidden in the fixture, not a fifth category. DO re-stamp the floor to NOW right before each later fire (tests/test_gh_reply_watch.py::_re_arm_floor — the mirror of the expiry test's back-dating), AFTER asserting the detector's stamp is >= the test's clock reading taken before the first fire — without that value check a `_mark_global_poll` writing `0` stays green (mutation-probed RED 2026-09-02); this keeps the claim causal and shrinks the timing assumption to one child's start-up.
