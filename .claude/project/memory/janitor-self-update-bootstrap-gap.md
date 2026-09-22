---
name: janitor-self-update-bootstrap-gap
description: "I shipped the release-triggered fast-update feature but the release that added it did NOT fast-update / after publishing vX the local plugin cache is still on vX-1 / why is the janitor cache behind GitHub right after a release / the version-update detector didn't request the update for its own release / why did v0.42.0 not fast-pull itself / can a self-updater accelerate its own first deployment / what is request_version_update / does the slow 6-hour version-update beat still apply after a fast-update ships / should I force claude plugin update from a session to fix a stale cache / why is forcing plugin update from N sessions a stampede / does a janitor-reload prove the cache actually rolled to the new version / how to verify the cache version with ls and claude plugin list / a reload marker is not proof of a new cache / I told the user the session runs the new hooks but the cache was still old / what is the fallback cadence for a self-update accelerator"
ocd: 2026-07-13
lmd: 2026-09-22
metadata:
  node_type: memory
  type: project
  tier: component
publish-globally: false
---

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
for the release-gate half (CPV, pre-push hook, version/branch recheck). [^1]

## Notes and lessons learned

[^1]: [id:ATOM-MG07-0017, status:valid, keywords:"reload_marker_not_proof_of_new_cache verify_version_dont_infer_from_marker ls_cache_and_plugin_list_settles_it", ocd:2026-07-13, lmd:2026-07-13] Found the day v0.42.0 shipped. I first told the user
  "the session now runs the 0.42.0 hooks" right after a `[janitor-reload]` — WRONG: the cache
  was still 0.41.0 (`claude plugin list` = 0.41.0, newest cache dir = 0.41.0), so the reload
  reloaded 0.41.0 and the running hooks were unchanged. I had asserted a state change without
  reading the state — the same partial-view-for-the-whole error that produced several false
  claims that day. The tell was cheap and I skipped it: one `ls <cache>` + one `claude plugin
  list` settles "did the cache actually roll?" in two commands. Lesson: a reload marker is a
  request to reload whatever is cached, NOT proof that something new was cached; verify the
  version, don't infer it from the marker.
