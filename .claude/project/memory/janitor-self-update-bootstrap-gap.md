---
name: janitor-self-update-bootstrap-gap
description: "I shipped the release-triggered fast-update feature but the release that added it did NOT fast-update / after publishing vX the local plugin cache is still on vX-1 / why is the janitor cache behind GitHub right after a release / the version-update detector didn't request the update for its own release / why did v0.42.0 not fast-pull itself / can a self-updater accelerate its own first deployment / what is request_version_update / does the slow 6-hour version-update beat still apply after a fast-update ships / should I force claude plugin update from a session to fix a stale cache / why is forcing plugin update from N sessions a stampede / does a janitor-reload prove the cache actually rolled to the new version / how to verify the cache version with ls and claude plugin list / a reload marker is not proof of a new cache / I told the user the session runs the new hooks but the cache was still old / what is the fallback cadence for a self-update accelerator"
ocd: 2026-07-13
lmd: 2026-07-13
metadata:
  node_type: memory
  type: project
  tier: component
---

A self-update mechanism **cannot accelerate its own first deployment.** When the
release-triggered fast-update (TRDD-Y9KM5RCJ, commit `5554a51`, first shipped in **v0.42.0**)
lands a new janitor version, the code that would *request* the fast pull runs from the
**cached (old) version's** detector — and the old version does not contain that code. So the
release that ADDS the fast-update path is itself pulled the slow way.

Concretely for v0.42.0: the cached 0.41.0 `version-update` detector has no
`gs.request_version_update()` (verified: `grep -r request_version_update <0.41.0 cache>` →
nothing; it exists only in the 0.42.0 tree). The per-session detector therefore cannot raise
the release-trigger for 0.42.0. The cache rolls to 0.42.0 only on the daemon's **slow 6-hour
`version-update` beat**, not the ~5-6 min fast path. The fast path works **from 0.42.0
onward** (0.42.0's detector can fast-pull 0.43.0).

**Why:** the mechanism is bootstrap-gated by construction — the accelerator lives in the
payload it is trying to accelerate. This is not a bug and there is nothing to "fix" in the
feature; it is logically unavoidable for any in-band self-updater. **How to apply:** after
publishing the FIRST release that contains a self-update/self-heal accelerator, expect that
release to arrive on the fallback cadence, and do NOT force `claude plugin update` from a
session to "fix" it — user-scope plugin updates are the daemon's single-writer job (issue #7,
PRRD S2.1); forcing it from N sessions is the stampede that invariant exists to prevent. Just
wait for the daemon's beat (or accept it lands at next SessionStart's natural update).

**The trap that pairs with this:** do NOT then assert "the session now runs the new hooks"
after a `[janitor-reload]` fires — verify the cache version first (`ls <cache>/…/ | sort -V |
tail -1` and `claude plugin list`). A `[janitor-reload]` can fire on a stale/premature
`reload-needed.flag` while the cache is unchanged, so the reload is a no-op on the OLD version
and the running hooks are still the old ones. Reload ≠ update. See [[janitor-publish-pipeline]]
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
