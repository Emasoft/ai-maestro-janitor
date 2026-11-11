---
name: claude-code-plugin-rollout-staleness
description: "the fix is published but the bug keeps happening / a session still injects the old behavior after the plugin updated / which sessions run stale hooks / an installed rule file went BACKWARD to an older version's content / why did / compact fire at the old threshold after the release / the fix is merged but the installed binary or rule is still the old one / cargo install left memgrep stale / memgrep --version reports the wrong commit / plugin code is SESSION-LOADED and a running session is a ghost of the old version until it reloads, and anything that INSTALLS (a Rust crate, a rule file, the plugin cache) needs its own delivery check on PATH / how do I tell which plugin version a session is actually running / a skill still loads from the old cached tree after reload-plugins ran / two plugin versions running in the same session / the detector still reports the pre-fix numbers after a release / the janitor daemon is dead but that might be correct because the server absorbed the chore / version-update-requested stays true forever / merged is not delivered / a self-reported version stamp lied about the actual code / why did the installed rule file revert to an older version / I shipped the release-triggered fast-update feature but the release that added it did NOT fast-update / after publishing vX the local plugin cache is still on vX-1 / why is the janitor cache behind GitHub right after a release / the version-update detector didn't request the update for its own release / why did v0.42.0 not fast-pull itself / can a self-updater accelerate its own first deployment / what is request_version_update / does the slow 6-hour version-update beat still apply after a fast-update ships / should I force claude plugin update from a session to fix a stale cache / why is forcing plugin update from N sessions a stampede / does a janitor-reload prove the cache actually rolled to the new version / how to verify the cache version with ls and claude plugin list / a reload marker is not proof of a new cache / I told the user the session runs the new hooks but the cache was still old / what is the fallback cadence for a self-update accelerator"
ocd: 2026-07-13
lmd: 2026-11-11
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: continuity
publish-globally: true
---

**Plugin rollout staleness** — why a shipped fix is NOT live everywhere the moment it is
published, and how to tell which sessions are ghosts. Governed by
[[claude-code-continuity-engineering]].

## The split (load-bearing)

| Surface | Rolls forward | When the fix lands |
|---|---|---|
| Heartbeat dispatcher (`dispatch.py` via the DATA-dir stub) | **auto** — the stub re-resolves the newest cached version on EVERY cron fire | next fire (~minutes), no reload needed |
| Global daemon | auto — `daemon_needs_restart()` restarts it from the new cache | ~minutes |
| **Hooks + skills + commands** | **SESSION-LOADED** — a running session keeps executing the OLD cached code | only after that session runs `/reload-plugins --force` (driven by the `[janitor-reload]` marker, per session) |

**The asymmetry bites twice.** A ghost session does not merely READ old code — its
SessionStart also WRITES. `install_rules` compared bytes and overwrote on ANY difference,
in EITHER direction, so the installed `~/.claude/rules/*.md` converged on whichever
session started LAST. Found live 2026-07-31: the installed heartbeat-protocol rule was
**0.60.1's** with 0.66.1 cached (26 versions on the host), so it did not document
`[janitor-quiet]` that the dispatcher emits — and the rule's own security clause tells an
agent to refuse an unlisted marker. Fixed in `442864c` (v1.0.0): each installed file leads
with `<!-- ai-maestro-janitor:rule-stamp version=X.Y.Z -->` and an install is REFUSED when
the installed stamp is newer. Every unknown fails toward INSTALLING — see [^2]. [^3]

## The ghost symptom

After v0.53.0 shipped the harness-relative compact threshold, a session still on 0.52.0
hooks injected `/compact` at the OLD 350k threshold — indistinguishable from "the fix
doesn't work" unless you know that session's LOADED version. Rule: **before declaring a
shipped fix broken, establish the misbehaving session's loaded plugin version.** [^1]

## Diagnosis

- A session's live loaded version is embedded in its hook execution paths:
  `~/.claude/plugins/cache/<marketplace>/<plugin>/<VERSION>/scripts/hooks/…` — the most
  recent hook exec per session IS its loaded version.
- Fleet-wide tooling requested from AgentlensPro (issue Emasoft/AgentlensPro#5, filed
  2026-07-18): `agentlenspro sessions --plugin <name>` → per-session loaded vs newest-cached
  + STALE flag; the janitor will consume it fail-open (`agentlens_probe`) to verify a pushed
  `[janitor-reload]` actually landed and to raise a per-project stale-hooks drift finding.

See also [[status-lines-to-autonomous-readers-cause-escalation]] — a fix published but not
installed is exactly the stranded-flag shape that page generalizes: a status line with
readers and no writers is where automatic remediation piles up.


^ATOM-14GY-NESV [desc:"a live ai-maestro server ABSORBS the update chore, so the janitor daemon correctly stands down — and if the server never consumes the request, the machine silently keeps running the old plugin", keywords: I_published_a_fix_but_the_cache_is_still_on_the_old_version the_janitor_daemon_is_dead_and_the_heartbeat_is_fine version-update-requested_stays_true_forever detectors_still_report_the_pre-fix_numbers_after_a_release who_actually_performs_the_plugin_update is_a_dead_daemon_always_a_bug why_did_the_server_absorb_the_update_chore should_I_hand_run_claude_plugin_update_myself the_pending_flag_never_clears grep_the_new_symbol_in_the_plugin_cache_to_confirm_delivery, type: project, ocd: 2026-08-01, lmd: 2026-08-01]

**A stalled update can be nobody's bug in progress.** When an ai-maestro server is alive
(`harness_backend.server_is_alive()`, from a fresh `~/.aimaestro/server-liveness.json`), it
ABSORBS the update trio, so `server_runs_chores()` is true and the janitor daemon deliberately
does not run. A dead daemon is then CORRECT, not a failure — and the per-session detector still
raises `version-update-requested`. If the server never consumes it, the flag simply stays set
and the machine keeps running the old plugin with no error anywhere.

Observed 2026-08-01: v2.2.0 published and green, and 71 minutes later the cache was still
2.1.0, the request still pending, daemon heartbeat 20h stale, server alive. The tell is that
DETECTORS KEEP REPORTING PRE-FIX NUMBERS — the memory-librarian still said 120 conflict
candidates when the shipped fix makes it 28, because the heartbeat runs the CACHED detector.
Confirm it directly rather than inferring: grep the new symbol in
`~/.claude/plugins/cache/.../<version>/scripts/...` and compare with the working tree.

Do NOT add a janitor-side fallback: the binary coordination rule (TRDD-LU0C5KAR) removed
exactly that guard, and this repo's contract says a running server that does not execute an
absorbed chore is a SERVER bug. Do NOT hand-run `claude plugin update --scope user` either —
user-scope writes belong to the single writer (issue #7 / PRRD S2.1). Escalate to the server
side; the pending flag is the evidence.


^ATOM-RGRE-T1Z7 [desc:"/reload-plugins does NOT re-point already-loaded skills — only a new session does; the cron path rolls forward while skills stay pinned", keywords: I_ran_reload-plugins_and_the_skill_is_still_the_old_version session_runs_new_detectors_but_old_skills two_plugin_versions_live_in_one_session reload_markers_delivered_but_nothing_changed only_a_new_session_picks_up_the_new_plugin skill_base_directory_shows_the_old_version why_did_reload-plugins_not_fix_the_skill does_clear_force_a_version_convergence how_many_times_did_reload-plugins_run_with_no_effect base_directory_for_this_skill_load_marker cron_detector_path_rolls_forward_but_skills_stay_pinned, ocd: 2026-08-06, lmd: 2026-08-06]

**A live session can run TWO plugin versions at once, and `/reload-plugins` does not fix it.** The auto-rolling dispatcher stub always resolves the NEWEST cached version, so the CRON/detector path rolls forward on its own — but SKILLS stay on whatever was current when the session loaded them. Result: new detectors and old skills in the same session, which reads as "the fix is published and the bug still happens".

MEASURED 2026-08-06 from `"Base directory for this skill:"` lines (real load markers, not prose):

| session | skill loads | `/reload-plugins` runs |
|---|---|---|
| overnight | 66 x 2.3.0, ZERO 2.4.1 | 27 |
| next day | 9 x 2.3.0, ZERO 2.4.1 | **23** |
| after `/clear` | 2 x 2.4.1, ZERO 2.3.0 | — |

Not one skill load resolved to the new version in either pre-clear session, though it had been cached for hours and one session ran `/reload-plugins` **23 times** — via a `janitor-reload-plugins` skill that was ITSELF loaded from the old tree. The fresh session after `/clear` picked up the new version on its first load.

So the janitor's convergence chain is NOT the suspect: cache update, reload-generation stamp, `[janitor-reload]` markers and the reload command all worked. **Only a NEW SESSION re-points skills** — which makes `/clear` + bootstrap the ONLY reliable version-convergence mechanism available, not merely a cost optimisation (TRDD-PXP08ZQC, TRDD-5C42VCUX).


^ATOM-RGRE-DIAG [desc:"to learn which plugin version a session is really running, read the skill LOAD MARKER's path — never ask a claim-state API", keywords: how_do_I_tell_which_plugin_version_a_session_runs which_version_is_this_session_actually_using claim_state_api_disagreed_with_reality base_directory_for_this_skill_path proving_what_actually_loaded claimed_chores_said_stood_down_but_the_log_says_otherwise an_api_reporting_ownership_is_not_a_record_of_execution grep_the_transcript_for_the_load_marker do_not_trust_a_claim-state_helper what_evidence_proves_a_skill_actually_loaded, ocd: 2026-08-06, lmd: 2026-08-06]

To establish which plugin version a session is ACTUALLY running, grep its transcript for `Base directory for this skill:` and read the version out of the PATH. That line is emitted at load time by the thing that did the loading, so it is evidence; a claim-state or install-registry helper describes INTENT and can disagree with what a live session holds.

Learned the expensive way on the same investigation: I first concluded the daemon had "stood down" for server-claimed update chores because `claimed_chores()` listed them — then found the daemon's own log showed it RAN the chore, with zero yield lines anywhere. The published root cause had to be withdrawn. An API that reports ownership is not a record of execution.


^ATOM-S5YC-CCW4 [desc: "Merged is not delivered: for anything that INSTALLS (a Rust crate, a rule file, a plugin) check the artifact on PATH, and do not trust its own version stamp", keywords: cargo_install_stale memgrep_version_wrong_sha merged_is_not_delivered installed_binary_older_than_the_fix build_stamp_lies rule_file_shipped_but_not_installed feature_works_in_repo_but_not_on_this_machine why_does_memgrep_dash_dash_version_report_the_wrong_commit build_rs_watched_git_HEAD_and_froze_the_stamp how_do_I_verify_an_installed_artifact_actually_contains_the_fix, type: reference, ocd: 2026-08-15, lmd: 2026-08-15]

**Merged is not delivered, and a version stamp is not evidence.** Anything that INSTALLS has a
second hop after the merge, and the janitor has three of them: the bundled `memgrep` crate
(`cargo install --path scripts/memgrep`), the global rules in `~/.claude/rules/`, and the plugin
cache itself. On 2026-08-16 two cards were closed with every acceptance box green while their code
had NOT reached this host by any test's reckoning — the check that settled it was invoking the
artifact on PATH, never re-reading the repo.

Worse, the artifact can lie about itself: `memgrep --version` reported `a685cca, 2026-08-07` for a
binary that demonstrably contained code committed 2026-08-14, because `build.rs` watched `.git/HEAD`
— a file a commit never writes — so the stamp froze at each checkout's FIRST build (TRDD-9XMPS8OZ,
fixed in `a698f163`). A frozen stamp is worse than none: it answers confidently in exactly the
situation it exists for.

So the delivery check is behavioural, in this order: run the thing by its BARE COMMAND NAME (a
repo-relative `./target/...` passes while PATH resolves elsewhere), assert on OUTPUT or a string
only the new code contains, and treat a self-reported version as a hint to corroborate — never as
the proof.


^ATOM-ARO4-DFBY [desc: "an uncommitted fix runs NOWHERE — a peer verifying it executes the cached published version, so continued symptoms are not evidence the fix failed", keywords: I_fixed_it_but_the_other_session_still_sees_the_bug a_peer_keeps_reporting_the_symptom_after_I_fixed_it is_my_fix_not_working_or_is_it_not_shipped the_heartbeat_runs_the_cached_plugin_not_my_working_tree dispatcher-stub_resolves_the_newest_cached_version uncommitted_tree_is_not_running_anywhere my_canary_will_not_flip_until_publish written_is_not_merged_is_not_delivered do_not_read_continued_symptoms_as_a_failed_fix verifying_a_fix_that_has_not_shipped another_project_measured_my_old_code, type: project, ocd: 2026-08-28, lmd: 2026-10-05]

**Written is not merged is not delivered, and the FIRST gap is the one that fools two parties at
once.** The heartbeat runs `dispatcher-stub.py`, which re-resolves the newest CACHED version under
`~/.claude/plugins/cache/…/ai-maestro-janitor/`. It never looks at the working tree. So a fix that
is green in `~/Code/…` runs on exactly zero sessions — including this project's own heartbeat —
until `publish.py` ships a version and it lands in the cache.


^ATOM-QCKN-E0C9 [desc: "after fixing a bug a peer reported, saying 'tell me if you still see it' misleads both sides: state the SHIP GATE, and a pure-function fix is the one exception a peer may test uncommitted", keywords: a_peer_keeps_seeing_the_bug_after_I_fixed_it tell_me_if_you_still_see_it_misleads_both_sides continued_symptoms_are_the_old_code_still_running state_the_ship_gate_with_a_fix-verification_request a_fix_blocked_from_publishing_is_not_delivered_work say_what_the_fix_is_blocked_on pure-function_fix_can_be_tested_on_an_uncommitted_tree never_point_a_peer_harness_at_an_uncommitted_tree_that_writes the_canary_will_not_flip_until_publish peer_advertised_a_dead_agent_for_seven_days side_effect_masquerading_as_a_measurement, type: project, ocd: 2026-10-05, lmd: 2026-10-05]

**The trap is the canary.** After fixing a bug a downstream session reported, it is natural to say
"tell me if you still see it". Both sides then read continued symptoms as the fix failing, when
they are just the old code still executing. Measured 2026-08-28: a peer project would have kept
being advertised a dead agent for the full 7-day backstop no matter how correct the fix was,
because its stub resolves the cache. It said so before I could misread its next report.

**So: state the SHIP GATE with any fix-verification request** ("this cannot be observed until a
version ships"), and when a fix is blocked from publishing, say what it is blocked ON — a fix that
cannot ship is not delivered work, however green its tests.

**A pure-function fix is the exception**, and the distinction is worth keeping: a peer CAN point
its harness at an uncommitted tree when the code under test only reads files and returns values
(`_scan` in the context-integrity detector). It must NOT for anything that writes — running
`dispatch`'s phases against a live session spends its nudge budget and touches its cadence state,
which is a side effect masquerading as a measurement.


^T5D46B8G [desc:"A self-update mechanism cannot accelerate its own first deployment: the release that adds the fast-pull path is itself fetched by the old cached detector, which lacks that code.", keywords:"self_update_cannot_accelerate_own_first_deployment fast_update_release_pulled_slow_way old_cached_detector_lacks_new_code trdd_y9km5rcj commit_5554a51 v0_42_0_first_shipped"]

A self-update mechanism **cannot accelerate its own first deployment.** When the
release-triggered fast-update (TRDD-Y9KM5RCJ, commit `5554a51`, first shipped in **v0.42.0**)
lands a new janitor version, the code that would *request* the fast pull runs from the
**cached (old) version's** detector — and the old version does not contain that code. So the
release that ADDS the fast-update path is itself pulled the slow way.


^FI4JZJ9S [desc:"Concretely for v0.42.0: the cached 0.41.0 detector had no request_version_update(), so it could not raise the release-trigger; the fast path only works from 0.42.0 onward.", keywords:"v0_42_0_concrete_example cached_0_41_0_detector_no_request_version_update per_session_detector_cannot_raise_trigger slow_6_hour_version_update_beat fast_path_works_from_0_42_0_onward"]

Concretely for v0.42.0: the cached 0.41.0 `version-update` detector has no
`gs.request_version_update()` (verified: `grep -r request_version_update <0.41.0 cache>` →
nothing; it exists only in the 0.42.0 tree). The per-session detector therefore cannot raise
the release-trigger for 0.42.0. The cache rolls to 0.42.0 only on the daemon's **slow 6-hour
`version-update` beat**, not the ~5-6 min fast path. The fast path works **from 0.42.0
onward** (0.42.0's detector can fast-pull 0.43.0).


^53GDCC00 [desc:"Why: the accelerator is bootstrap-gated by construction, living in the payload it accelerates - not a bug. How to apply: never force claude plugin update from a session; wait for the daemon's beat.", keywords:"bootstrap_gated_by_construction_not_a_bug accelerator_lives_in_its_own_payload do_not_force_claude_plugin_update_from_session daemon_single_writer_job issue_7 prrd_s2_1 stampede_the_invariant_prevents wait_for_daemon_beat"]

**Why:** the mechanism is bootstrap-gated by construction — the accelerator lives in the
payload it is trying to accelerate. This is not a bug and there is nothing to "fix" in the
feature; it is logically unavoidable for any in-band self-updater. **How to apply:** after
publishing the FIRST release that contains a self-update/self-heal accelerator, expect that
release to arrive on the fallback cadence, and do NOT force `claude plugin update` from a
session to "fix" it — user-scope plugin updates are the daemon's single-writer job (issue #7,
PRRD S2.1); forcing it from N sessions is the stampede that invariant exists to prevent. Just
wait for the daemon's beat (or accept it lands at next SessionStart's natural update).


^MT4R942H [desc:"The trap that pairs with this: do not assert the session runs new hooks after a janitor-reload fires without verifying cache version first - reload can be a no-op on a stale flag.", keywords:"trap_reload_not_proof_of_update do_not_assert_new_hooks_without_verifying verify_cache_version_ls_and_plugin_list janitor_reload_can_fire_on_stale_flag reload_is_a_noop_on_old_version reload_not_equal_update"]

**The trap that pairs with this:** do NOT then assert "the session now runs the new hooks"
after a `[janitor-reload]` fires — verify the cache version first (`ls <cache>/…/ | sort -V |
tail -1` and `claude plugin list`). A `[janitor-reload]` can fire on a stale/premature
`reload-needed.flag` while the cache is unchanged, so the reload is a no-op on the OLD version
and the running hooks are still the old ones. Reload ≠ update. See [[janitor-publish-pipeline-gate-sequence]]
for the release-gate half (CPV, pre-push hook, version/branch recheck). [^4]

## See also

- [[janitor-self-update-bootstrap-gap]]
- [[plugin-cache-install-integrity]] — the sibling failure: there the CACHE itself is
  incomplete (an install killed partway), so components are missing on disk; here the cache
  is complete and only the LOADED skills are stale. Tag-diff the cache to tell them apart.
- [[janitor-publish-pipeline-gate-sequence]]

## Notes and lessons learned

[^1]: [id:ATOM-ROLL-GHOST, status:valid, keywords:"fix published but bug still happening stale hooks session loaded old version reload-plugins ghost", ocd:2026-07-18, lmd:2026-07-18]
  DO NOT debug a "still-broken after the release" report against the new code, BECAUSE hooks
  are session-loaded and the misbehaving session may be a ghost running the previous version
  until its reload lands. DO check the session's loaded version first (hook exec paths embed
  it), then re-test only if the ghost hypothesis fails.

[^2]: [id:ATOM-ROLL-M0N0, status:valid, keywords:"installed_file_went_backward older_session_overwrote_newer byte_compare_overwrites_either_direction contract_not_monotonic rule_stamp", ocd:2026-07-31, lmd:2026-07-31]
  DO NOT decide "install or skip" by comparing BYTES when the executable half auto-rolls
  FORWARD, BECAUSE a byte difference is direction-blind: any older session on the host then
  reverts the newer contract, making every shipped rule fix revertible rather than merely
  late. DO stamp the writer's version into the artifact and refuse an older writer.

[^3]: [id:ATOM-ROLL-UNKN, status:valid, keywords:"unknown_version_fail_direction guard_froze_the_file placeholder_0_0_0_outranked_unknown", ocd:2026-07-31, lmd:2026-07-31]
  DO NOT let a monotonic guard fail toward REFUSING on an unreadable version, BECAUSE a file
  it can never overwrite again is the same permanent-staleness failure the guard exists to
  prevent, inverted. DO fail toward INSTALLING on every unknown, and write the literal
  `unknown` rather than `0.0.0` — a placeholder that PARSES would outrank a genuinely unknown
  source on the next install and freeze the file for real.
[^4]: [id:ATOM-MG07-0017, status:valid, keywords:"reload_marker_not_proof_of_new_cache verify_version_dont_infer_from_marker ls_cache_and_plugin_list_settles_it", ocd:2026-07-13, lmd:2026-07-13] Found the day v0.42.0 shipped. I first told the user
  "the session now runs the 0.42.0 hooks" right after a `[janitor-reload]` — WRONG: the cache
  was still 0.41.0 (`claude plugin list` = 0.41.0, newest cache dir = 0.41.0), so the reload
  reloaded 0.41.0 and the running hooks were unchanged. I had asserted a state change without
  reading the state — the same partial-view-for-the-whole error that produced several false
  claims that day. The tell was cheap and I skipped it: one `ls <cache>` + one `claude plugin
  list` settles "did the cache actually roll?" in two commands. Lesson: a reload marker is a
  request to reload whatever is cached, NOT proof that something new was cached; verify the
  version, don't infer it from the marker.
