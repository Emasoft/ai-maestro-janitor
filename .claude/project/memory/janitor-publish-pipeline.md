---
name: janitor-publish-pipeline
description: "publish blocked / how do I release the janitor / CPV flagged a finding / can I skip a gate / push rejected by pre-push hook / version mismatch on publish / no changelog / publish exited 3 but every test passed / rc=3 with nothing failing — the janitor's fail-fast publish pipeline (a CPV plugin), its gate order, the write-guard, and the CPV-only validate policy"
ocd: 2026-06-13
lmd: 2026-07-22
metadata:
  node_type: memory
  type: project
  tier: component
  globs:
    - "scripts/publish.py"
    - "cliff.toml"
    - "CHANGELOG.md"
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
   package.json / Cargo.toml / Python `__version__`; a mismatch aborts.
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
/ linear history with NO bypass actor; pr-and-checks: PR ≥ 1 approval + required
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

## See also

- `[[project_janitor_publish_blocked_cpv_fps]]` — the publish-gate history + the
  devitalize-or-remove unblock recipe (RESOLVED; v0.7.x shipped).
- `[[janitor-self-update-bootstrap-gap]]` — the OTHER half of a release: after publish.py
  succeeds, why the local cache can stay on the old version (the fast-updater can't
  accelerate its own first release; reload ≠ update).

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
degrades to "no other actor", i.e. it blames the suite.


^ATOM-UHO6-Q99D [desc:"gate 4 timing out is CPV's worker-pool startup race, not a too-tight cap — retry, do not raise it", keywords: publish_hangs_at_gate_4_validating_plugin_remote_CPV Command_timed_out_after_300s publish_fails_but_every_test_passed REPO_LINT_never_finishes cpv-remote-validate_stuck, type: project, ocd: 2026-07-28, lmd: 2026-07-28]

Gate 4 (`stage_validate`, remote CPV) can HANG, and its 300s cap is the thing that catches it — do
not read a timeout there as "the cap is too tight". CPV`s `[REPO LINT]` stage fans out a worker pool;
when the ~15 workers spawn it finishes in ~60s, but when they fail to spawn the parent blocks on a
lock forever instead of raising `BrokenProcessPool`. It is a startup RACE, so it is intermittent: two
consecutive publishes died at 300s and the very next run passed clean (EXIT=0, 0 blocking issues).
Diagnose it in one step rather than guessing — `/usr/bin/sample <pid> 4` shows the main thread at
3317/3317 samples in `lock_PyThread_acquire_lock -> acquire_timed -> __psynch_cvwait` with threads
parked in `_queue_SimpleQueue_get`, and `ps` shows a `multiprocessing.resource_tracker` child with
ZERO workers beside it. The remedy is to RETRY the publish; there is no `--jobs`/serial flag to pass. [^5]

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
