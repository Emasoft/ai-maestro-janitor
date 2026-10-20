---
name: janitor-publish-pipeline
description: "publish blocked / how do I release the janitor / CPV flagged a finding / can I skip a gate / push rejected by pre-push hook / version mismatch on publish / no changelog / publish exited 3 but every test passed / rc=3 with nothing failing / the gate timed out but the test passes on its own / TimeoutExpired on an xdist worker / is this flaky or a real regression — the janitor's fail-fast publish pipeline (a CPV plugin), its gate order, the write-guard, and the CPV-only validate policy / the test gate blocks a publish at random / tests fail only in the full suite and pass alone / a detector exits 0 with empty stdout / assert something in an empty string / which load-flake category is this / should I scale every timeout call site or enumerate them / enumerating call sites keeps missing some / scale timeouts at a seam not per site / my timeout scaling looks applied but does nothing / a module-level constant reads the env before the fixture sets it / timeout_scale frozen at 1.0 / a vacuous fix that looks scaled / gh-reply-watch floor test flaked under load / two projects reported the same reply / the deferred project polled again / a wall-clock floor spanning sequential spawns / I checked the gate would pass but it blocked anyway / hand-wrote a regex to approximate the lint / how do I dry-run the address lint before publishing / phantom hits from a stub known_for / an email-shaped filename blocked the release / dot-invalid is allow-listed but the publish still blocked / the release tag points at an old commit / tag and HEAD disagree after publish / duplicate chore bump version commits on main / publish exited 0 but the tag is wrong / renamed a test file and the address lint exploded / grandfathered addresses stopped being grandfathered / publish exited 4 / NIT blocked by strict / markdownlint MD011 / no-reversed-links / a lint error in a card blocks the release / the exemption is not sufficient / three blockers stop a release / steps 5-11 never ran on this tree"
ocd: 2026-06-13
lmd: 2026-10-20
metadata:
  node_type: memory
  type: project
  tier: hub
  globs:
    - "scripts/publish.py"
    - ".cpv-version"
    - "cliff.toml"
    - "CHANGELOG.md"
publish-globally: false
split-lineage: 08b34684a6214833bc3d78b80244d2cd
---

# ai-maestro-janitor — publish pipeline hub

^0O2J92RS [desc:"The janitor ships via scripts/publish.py, a strict fail-fast release pipeline; as a CPV plugin it includes the CPV schema + security gate; any gate failure stops the release - no skip/force/bypass.", keywords:"janitor_ships_via_scripts_publish_py strict_fail_fast_release_pipeline cpv_plugin_schema_security_gate any_gate_failing_stops_release no_skip_no_force_no_bypass"]
The janitor ships via `scripts/publish.py` — a strict, **fail-fast** release
pipeline. **It is a CPV plugin**, so its pipeline includes the CPV plugin-schema
+ security gate; any gate failing exits non-zero and the release stops — there
is no skip, no force, no bypass.

## Parts map

This page is the entry point; the detail lives in four sub-pages (split from
this page on 2026-09-05 — it had outgrown a single load). Each still carries
its own lessons-learned section and links back here.


^ATOM-6WEW-R28X [desc: "an UNRELEASED fix cannot fix this machine: the heartbeat runs the newest CACHED plugin version, so a committed fix is invisible until it is published", keywords: unreleased_fix_not_live the_fix_is_committed_but_the_bug_still_happens the_machine_runs_old_code dispatcher_stub_re-resolves_newest_cached_version 599_commits_ahead_of_the_release alert_keeps_repeating_after_the_fix_is_written release_gap board_drain_rule_blocks_the_release repo-state_LOW_advisory_does_not_escalate PLUGIN_SKIP_GITHUB_INTEGRITY CPV_integrity_manifest_mismatch No_publish_until_the_board_is_drained 3451_mismatching_files, ocd: 2026-10-19, lmd: 2026-10-19]

THE RELEASE GAP, measured 2026-10-20 (TRDD-PWL9GD4E, TRDD-5CGPEK4V, TRDD-U0VLVJVT).

A fix COMMITTED but NOT PUBLISHED does not exist for the janitor. The dispatcher
stub (the plugin DATA dir's `dispatcher-stub.py`) re-resolves the newest CACHED
version directory on EVERY fire and `os.execv`s into it, so the running code is
the newest PUBLISHED build — never the working tree. A published release alone
is not enough either: the new version must land in the plugin CACHE.

THE LOOP, self-perpetuating and invisible: alert repeats -> an agent diagnoses
it correctly -> the agent writes and commits the fix -> the fix sits in the tree
-> the heartbeat keeps running the old build -> the alert keeps repeating. Each
cycle produces a better commit and the SAME alert, and the alert is the only
thing the owner actually sees. DO NOT read a repeated alert as an unfixed
defect: FIRST check whether the fix is already on main and merely unreleased.
Measured 2026-10-20: 599 commits sat on main after v3.8.11, and the fix for the
owner's complaint was `f795816c` (TRDD-JWIGGMH0, 2026-10-19) — on main, not an
ancestor of the release, absent from the installed build.



^ATOM-N44N-KU9B [desc: "at least THREE blockers stop a release on this tree, and only one is a real decision: the CPV integrity abort is bypassable, a step-4 NIT is NOT bypassable, and the board-drain rule is the owner's", keywords: publish_blocked what_stops_the_release CPV_integrity_manifest_mismatch 3451_mismatching_files PLUGIN_SKIP_GITHUB_INTEGRITY No_publish_until_the_board_is_drained board_drain_rule carve-out_for_live_owner_complaint publish.py_step_4_of_11 TRDD-S6GX1DHN TRDD-CWKM5218 TRDD-U0VLVJVT how_do_I_release_the_janitor publish_exited_4 NIT_blocked_by_strict exemption_is_not_sufficient three_blockers step_5_to_11_never_ran publish_failed_on_NIT NIT_blocks_publish markdownlint_MD011 exit_4 step_4_NIT repo-state_LOW_advisory_never_escalates the_NIT_fix_is_one_line, ocd: 2026-10-19, lmd: 2026-10-20]
AT LEAST THREE BLOCKERS STOP A RELEASE ON THIS TREE, and only one is a real decision.

1. THE CPV VALIDATOR'S OWN INTEGRITY CHECK aborts at publish step 4 of 11 with
   "[CPV integrity] CRITICAL: integrity manifest mismatch" and 3451
   mismatching files. Cause is upstream (TRDD-CWKM5218). `publish.py` exempts it
   via `PLUGIN_SKIP_GITHUB_INTEGRITY=1`; every release from 3.7.1 to 3.8.11
   shipped under it, so it is BYPASSABLE.

2. A STEP-4 NIT, WHICH THE EXEMPTION DOES NOT TOUCH, so it is NOT bypassable.
   Measured 2026-10-20 01:31: the exempted dry-run COMPLETED and FAILED —
   exit 4, "NIT issues found - blocked by --strict", SUMMARY: CRITICAL=0
   MAJOR=0 MINOR=0 NIT=1 WARNING=42. The exemption is therefore NECESSARY BUT
   NOT SUFFICIENT. `publish.py` sanctions no env var for a NIT (the exemption set
   is exactly PLUGIN_SKIP_GITHUB_INTEGRITY and CPV_SKIP_GH_AUTH_CHECK), so the
   content must be FIXED. That fix is one line, and it is COMMITTED (9f9cfbc4) as
   of 2026-10-20, so the NIT is expected to clear on the next run — which is an
   inference, not a measurement, until the gate is re-run.

   AND THE GATE HAS NEVER BEEN OBSERVED TO COMPLETE ON THIS TREE: the exempted
   run died at the END of step 4, so steps 5-11 have never run here and
   a further blocker may sit in any of them.

3. THE PROJECT RULE on TRDD-S6GX1DHN: "No publish until the board is drained."
   The board is ~344 cards, so this is the REAL blocker — and it is the OWNER's
   decision, not a tooling failure. The rule has NO carve-out for a fix that
   answers a LIVE owner complaint (TRDD-U0VLVJVT carries the proposed text). [^1]

DO NOT CONFLATE THEM. `repo-state` reports unreleased commits, but it sits in `_ADVISORY_DETECTORS` ("informational: ... never an incident") and the quiet filter records such lines as `sev="LOW"` — a repo whose SHIPPED artifact is hundreds of commits behind its own working tree is reported at the same severity as a merely dirty repo. On this tree, no detector escalates this class.

## Applies to


- [[janitor-publish-pipeline-gate-sequence]] — the full gate order (Step 0
  through Step 14), the CPV-only validation policy (devitalize-or-remove,
  never suppress), the admin-bypass branch-ruleset model, and the `--dry-run`
  / run-form contract.
- [[janitor-publish-pipeline-gate-timeouts-and-flakiness]] — the four
  categories of test-gate load-flake, the REAL-STATE write-guard's rc=3
  signature, gate-4 CPV-validate timeouts (hang vs slow vs host-saturation),
  and the tree-freeze / publish-lock enforcement.
- [[janitor-publish-pipeline-address-lint]] — the `[G1b]` personal-address
  lint: how it scopes to added lines, its false positives (email-shaped
  filenames, file renames), and how to dry-run it before a real publish
  attempt.
- [[janitor-publish-pipeline-cpv-and-release]] — CPV `--strict`
  frontmatter/pin gates, the release-tag drift after an interrupted-publish
  recovery, the card-acceptance chicken-and-egg with a live-observation box,
  and why a green publish gate is not evidence the CI-judged release is good.

## See also

- `[[project_janitor_publish_blocked_cpv_fps]]` — the publish-gate history + the
  devitalize-or-remove unblock recipe (RESOLVED; v0.7.x shipped).

## Notes and lessons learned

[^1]: [desc: "a markdownlint MD011 in a card can BLOCK the publish, and the exemption does not cover it", keywords: publish_exited_4 NIT_blocked_by_strict markdownlint_MD011 no-reversed-links a_card_blocks_the_release markdownlint_error_in_a_TRDD the_publish_is_blocked_by_a_lint_error reversed_link_syntax MD011_in_design backtick_the_slice_expression a_NIT_is_not_bypassable, ocd: 2026-10-19, lmd: 2026-10-20, id: ATOM-2TG0-CEAK, status: valid] DO NOT read the CPV integrity exemption as SUFFICIENT to reach a release, BECAUSE `--strict` blocks on a NIT too, and `publish.py` sanctions NO env var for one (the exemption set is exactly PLUGIN_SKIP_GITHUB_INTEGRITY and CPV_SKIP_GH_AUTH_CHECK). Measured 2026-10-20 01:31: the exempted dry-run cleared the integrity check and then FAILED at the end of step 4 with exit 4 — "NIT issues found - blocked by --strict", SUMMARY: CRITICAL=0 MAJOR=0 MINOR=0 NIT=1 WARNING=42. The NIT was one markdownlint MD011 in a TRDD card added 2026-10-18 (absent at v3.8.11, whose released tree linted clean over 792 files) — so it was NEW in the unreleased tree. THE MD011 MECHANISM, since it recurs in any card that quotes a Python slice or a list index: MD011 is `no-reversed-links` and it fires on a CLOSING PAREN IMMEDIATELY FOLLOWED BY AN OPENING BRACKET — `f(x)[0]`, `sha256(action)[:12]`. Isolated by linting each minimal form: `f(x)[0]` trips it, `[x](y)` does NOT (that is the normal link order). The reported text reads as `[(x)[0]]` because markdownlint re-groups the pair. A code span is exempt, so backticking the expression clears it: `sha256(action)[:12]`. The repo's `.markdownlint.json` does not disable MD011, and the gate lints the design tree, so any card carrying a bare `)[...]` construct blocks the publish. DO fix the CONTENT, DO NOT hunt for a second bypass: a third failure tends to produce pressure for a third exemption, and the correct response is a content fix. Note also that the gate has NEVER been observed to complete on this tree — the exempted run died at the end of step 4, so steps 5-11 (marketplace registration, version consistency, version bump, README badge, changelog, commit+push, GitHub release) have never run here, and a further blocker may sit in any of them.
