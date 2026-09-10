---
name: janitor-publish-pipeline-cpv-and-release
description: "the release tag points at an old commit / tag and HEAD disagree after publish / duplicate chore bump version commits on main / publish exited 0 but the tag is wrong / CPV flagged a finding / Malformed YAML frontmatter on a SKILL.md / publish blocked by a MAJOR about a non-resolvable CPV ref / a card cannot be completed before release / publish is a mid-pipeline step not the finish line / publish said green but CI went red / is publish.py the same as CI / a green publish is not evidence the release is good / which checks does the publish gate actually run / bumping the CPV version / how do I dry-run the candidate CPV pin before publishing / interrupted-publish recovery left a stale tag"
ocd: 2026-08-01
lmd: 2026-09-10
metadata:
  node_type: memory
  type: project
  tier: component
  globs:
    - ".cpv-version"
    - "cliff.toml"
    - "CHANGELOG.md"
publish-globally: false
split-lineage: 08b34684a6214833bc3d78b80244d2cd
---

# janitor-publish-pipeline — CPV `--strict`, version pin, release-tag drift & CI mismatch

^ATOM-MNT1-0BBX [desc: "CPV CRITICAL 'Malformed YAML frontmatter' on a SKILL.md = an unquoted ': ' inside the plain-scalar description; tests/test_skill_frontmatter_yaml.py now parses every skill locally", keywords: Malformed_YAML_frontmatter missing_closing_---_or_invalid_YAML mapping_values_are_not_allowed_here skill_description_contains_colon_space unquoted_colon_in_yaml_description SKILL.md_frontmatter_CRITICAL cpv_rejects_a_skill_frontmatter publish_blocked_by_skill_frontmatter quote_the_description_or_drop_the_colon test_skill_frontmatter_yaml skill_frontmatter_guard_test yaml_safe_load_every_SKILL.md, type: project, trdd: TRDD-VMXAF9IY, ocd: 2026-09-03, lmd: 2026-09-03]

CPV `--strict` raised `[CRITICAL] Malformed YAML frontmatter (missing closing --- or invalid YAML)` on `skills/janitor-gitignore-fix/SKILL.md` (shipped in ede9bdb4). Cause: the plain-scalar `description:` contained `Plan-first: shows …` — an unquoted `: ` inside a plain scalar in a block mapping is invalid YAML (`yaml.safe_load` → `mapping values are not allowed here`). No local gate parsed skill frontmatter, so it surfaced only at publish time. Fix: drop the `: ` (or quote the scalar). Guard: `tests/test_skill_frontmatter_yaml.py` parses every `skills/*/SKILL.md` frontmatter with `yaml.safe_load` and requires `description` to be a plain non-empty string — the next such typo fails `pytest`, not the release.




^ATOM-VA75-PD8K [desc: "A card whose last acceptance box is 'observe it live' is unblocked BY the release, so publish is a mid-pipeline step, not the finish line", keywords: card_cannot_be_completed_before_release blocked-live_acceptance_box observe_it_live_in_production publish_before_completing_all_TRDDs board_will_not_drain_before_publish last_box_needs_a_live_run rc=0_only_after_publish waiting_for_a_live_wall unpublished_fix_still_failing why_is_the_card_stuck_at_testing complete_all_cards_then_publish chicken_and_egg_publish_gate, type: project, ocd: 2026-09-03, lmd: 2026-09-03]
Several janitor cards carry a final acceptance box that can only be ticked by OBSERVING the
shipped code run on this machine — a `marketplace-refresh` run that exits `rc=0`, a rotation
that ends with the pane back at `idle`, a `/model` switch that fires the hook. The daemon runs
the INSTALLED plugin, not the working tree, so none of those can happen until the commit is in
a published version.

So "finish every card, then publish" is unsatisfiable as stated: the release is what makes the
last box observable. The correct order is to complete every box that code and tests can close,
publish, then let the live boxes tick on their own evidence afterwards.

What was actually measured, 2026-09-03 (state the sample, not a round number): of 16 cards at
`column: testing`, subagent triage judged 10 BLOCKED-LIVE; of 8 fix commits whose tag
containment was checked by hand, 6 were in NO tag and 2 were already published
(TRDD-X6I04SAO in v3.4.13, TRDD-2F3I2P18 in v3.4.10). So "publish-gated" is the common case
here, not the universal one — a BLOCKED-LIVE card can also be waiting on an event that the
already-shipped code simply has not produced yet.

Check containment against the REMOTE (`git ls-remote --tags origin`), not `git tag --contains`
alone: the latter only sees tags this clone has fetched, so an unfetched release reads as
unpublished. And do not identify "the fix commit" with `git log -1 --grep=<id>` — that returns
the NEWEST commit mentioning the card, which is often a docs commit, so you end up testing the
publication of documentation rather than of code.




^ATOM-YI5I-55H6 [desc: "interrupted-publish recovery re-bases the version bump on the remote but REUSES the stale local tag, so the release tag can name a commit several behind the pushed main", keywords: the_release_tag_points_at_an_old_commit git_tag_v3.4.14_is_behind_origin_main interrupted_publish_recovery_left_a_stale_tag local_plugin.json_is_at_X_but_origin_is_at_Y using_remote_as_bump_baseline duplicate_chore_bump_version_commits_on_main the_release_does_not_contain_my_last_commit tag_and_HEAD_disagree_after_publish does_the_released_tag_carry_my_fix publish_exited_0_but_the_tag_is_wrong, type: project, ocd: 2026-09-03, lmd: 2026-09-03]

When a publish is interrupted AFTER `[G1] version bump` created the local tag but BEFORE the push, the next run prints `Local plugin.json is at <N> but origin is at <N-1> — using remote as bump baseline (interrupted-publish recovery)` and re-bumps to the SAME version, producing a second `chore: bump version to <N>` commit — but it does NOT re-point the pre-existing local `v<N>` tag, so the tag it pushes names the FIRST bump commit. Measured 2026-09-04: `v3.4.14` landed on `cc6bc25a` while `origin/main` was `4326519d`, four commits ahead. Benign that day, measured with `git diff --stat v3.4.14..origin/main`: exactly three files differ (CHANGELOG.md and two test modules, 17 insertions / 2 deletions), nothing under `scripts/`, and `plugin.json` is absent because both bump commits set the same version. A functional commit in that window would instead ship a release missing it. ALWAYS verify after a recovered publish: `git rev-parse v<N>^{commit}` vs `git rev-parse origin/main`, and `git log --oneline v<N>..origin/main`. [^17] [^20]




^ATOM-01KZ-DNOF [desc: "the release gate is NOT a superset of CI and publishes before CI judges the pushed sha — a green publish.py is not evidence the release is good", keywords: publish_said_green_but_CI_went_red ci_failed_on_the_commit_I_just_released the_gate_passed_and_github_rejected_it pyright_errors_after_a_successful_publish is_publish.py_the_same_as_CI red_badge_on_a_released_tag gate_runs_ruff_and_mypy_CI_runs_ruff_and_pyright release_created_before_CI_ran which_checks_does_the_publish_gate_actually_run my_release_is_public_and_CI_is_failing, type: project, ocd: 2026-09-03, lmd: 2026-09-03]

`publish.py`'s gate and `.github/workflows/ci.yml` check DIFFERENT things, and the gate is the smaller set. Measured 2026-09-04 on the `--patch` run that shipped 3.4.14 (from that run's own `$` echoes vs ci.yml): the gate ran `ruff check scripts/` where CI runs `ruff check scripts/ tests/`; the gate ran NO pyright where CI runs bare `uvx --with pyright pyright` over the whole project with no continue-on-error; and the gate skips shellcheck, CI's separate serial `-m integration` pytest run, the hooks.json/dispatch/hook/detector smoke runs, and the memgrep staging. mypy is gate-only, which is fine — pyproject.toml documents the mypy/pyright split as deliberate (TRDD-BMDZK4RA: mypy cannot check `scripts/lib/` sibling calls, pyright owns that class). CI rejected `4326519d` with 7 pyright errors, all in `tests/` — the directory the gate's ruff does not read either. Worse than the missing checks: publish.py tags, pushes, creates the GitHub release and installs before CI has judged the pushed sha, so the release was public, installed, and the daemon had respawned onto it before the red badge appeared. Card: TRDD-MYQGMAQZ. [^19]



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
enforcement into a test, where duplication becomes checked rather than trusted. [^15]


## Governed by

- [[janitor-publish-pipeline]] — the publish-pipeline overview hub this page details.

## Notes and lessons learned
[^15]: [id: ATOM-7DRY-XQ73, status: valid, desc: "a stale CPV pin rejects a NEW hook event as CRITICAL — validate the candidate pin against the tree, then move the pin with the SSOT test", keywords: "Unknown_hook_event PostModelSwitch_rejected_by_CPV CRITICAL_Unknown_hook_event_did_you_mean new_hook_event_blocks_the_publish cpv-version_pin_too_old_for_a_new_hook which_CPV_version_knows_the_hook_event bump_the_CPV_pin_safely validate_the_candidate_cpv_ref_before_bumping hooks.json_registration_rejected CC_2.1.251_hook_event_not_in_CPV_allowlist PreModelSwitch_PostModelSwitch_cpv", ocd: 2026-09-03, lmd: 2026-09-03] DO NOT register a new Claude Code hook event in hooks/hooks.json (e.g. `PostModelSwitch`, CC 2.1.251) while `.cpv-version` pins a CPV release that predates the event, BECAUSE the pinned validator rejects it as `[CRITICAL] Unknown hook event` and every publish is red until the pin moves — measured 2026-09-03: pin v5.4.0 (70+ releases behind) rejected it, v5.15.0+ accepts it (`cpv_validation_common.py` allowlist). DO run the candidate pin against the tree FIRST (`uvx --from git+https://github.com/Emasoft/claude-plugins-validation@vX.Y.Z --with pyyaml cpv-remote-validate plugin . --strict` must print `SUMMARY: CRITICAL=0 MAJOR=0 MINOR=0 NIT=0`), then bump `.cpv-version` + the two workflow literals and run `tests/test_cpv_pin_ssot.py`.
[^17]: [id: ATOM-A0TX-M8TC, status: valid, keywords: "publish_exited_0_but_the_tag_is_wrong the_release_tag_points_at_an_old_commit tag_and_HEAD_disagree_after_publish duplicate_chore_bump_version_commits_on_main does_the_released_tag_carry_my_fix interrupted_publish_recovery_left_a_stale_tag using_remote_as_bump_baseline git_rev-parse_tag_vs_origin_main the_release_does_not_contain_my_last_commit verify_the_tag_after_a_recovered_publish", ocd: 2026-09-03, lmd: 2026-09-03] DO NOT treat `Published <N> successfully!` plus a green `Verified on remote: v<N>` as proof the release carries your latest commit, BECAUSE the recovery path re-bases the VERSION on the remote but reuses the pre-existing local TAG, and the remote verification only checks the tag EXISTS — measured 2026-09-04, `v3.4.14` resolved four commits behind the `main` the same run had just pushed. DO run `git log --oneline v<N>..origin/main` after any publish that printed `interrupted-publish recovery`, and read the commits it lists before believing the release is complete.
[^19]: [id: ATOM-D69H-TWT9, status: valid, keywords: "publish_said_green_but_CI_went_red the_gate_passed_and_github_rejected_it a_green_publish_is_not_a_good_release ci_failed_on_the_commit_I_just_released release_created_before_CI_ran is_publish.py_the_same_as_CI red_badge_on_a_released_tag which_checks_does_the_publish_gate_actually_run my_release_is_public_and_CI_is_failing gate_runs_ruff_and_mypy_CI_runs_ruff_and_pyright", ocd: 2026-09-03, lmd: 2026-09-03] DO NOT read "All gates passed" from publish.py as evidence the release is good, BECAUSE the gate is a strict SUBSET of CI and runs BEFORE the artifact is judged — measured 2026-09-04, 3.4.14 was tagged, released, installed and picked up by the daemon while CI was failing the same commit on 7 pyright errors the gate never looked for. DO NOT answer this with a habit of checking — until TRDD-MYQGMAQZ lands, a green gate simply proves less than it appears to, and a lesson prescribing manual vigilance where a control belongs will be recalled AFTER the next failure, not before. Treat the red badge as the gate's verdict on itself. Read the EMITTER (the run's echoes), never the prose describing what the gate "runs".
[^20]: [id: ATOM-NMSI-8OVE, status: valid, keywords: "duplicate_3.x.y_section_in_CHANGELOG git-cliff_emits_two_sections_same_version stale_local_tag_interrupted_publish changelog_wrong_after_publish_recovery cliff_bump_sees_old_tag_as_released delete_stale_local_tag_before_rerun git_ls-remote_tags_before_deleting why_does_CHANGELOG_have_two_entries_for_the_same_version re-running_publish_after_interruption_duplicated_changelog git_tag_-d_before_retrying_publish.py", ocd: 2026-09-10, lmd: 2026-09-10] DO NOT re-run publish.py to recover an interrupted publish while the stale LOCAL v<N> / <plugin>--v<N> tags from the failed run still exist, BECAUSE step 9 runs git-cliff --bump --tag v<N> BEFORE step 10's _stale_tag_plan retag, so cliff sees the old tag as released and emits TWO ## [<N>] sections (measured 2026-09-10 on 3.5.0 by dry run). DO first prove the tags are unpublished (git ls-remote --tags origin refs/tags/v<N> must exit 0 AND print nothing), then git tag -d both local tags, then re-run — step 10 mints fresh annotated tags at HEAD.
