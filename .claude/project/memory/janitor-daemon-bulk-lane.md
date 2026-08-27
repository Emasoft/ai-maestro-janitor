---
name: janitor-daemon-bulk-lane
description: "oauth rotation missed / account hit rate limit wall while janitor was running — daemon blind for 20 minutes / task stamps frozen but heartbeat fresh / marketplace-refresh runs back to back / why are bulk tasks detached children / why did the daemon miss an oauth rotation window / marketplace-refresh cadence equals its own runtime causing back-to-back runs / what is the bulk lane in daemon.py / which tasks run background=True detached child / why is .last-run.ts frozen while daemon.heartbeat.ts is fresh / does a bulk task block the 60 second survival beats / what is _BULK_RECHECK_SEC / never set task cadence near its worst-case runtime / monkeypatched CLAUDE_PROJECT_DIR ignored in tests lru_cache project_root / test wrote into the real repo .janitor state seen file"
ocd: 2026-07-17
lmd: 2026-07-17
metadata:
  node_type: memory
  type: project
  tier: component
publish-globally: false
---

**The daemon's due-loop is single-threaded; since v0.50.0 (TRDD-H7NVKSAX) the BULK tasks
(`marketplace-refresh`, `fleet-plugins-update`, `version-update`, `github-config-audit`;
`user-plugins-update` was one until its 2026-08-20 retirement, TRDD-E39YT9G6)
carry `background=True` and run in ONE detached, parent-reaped child at a time (the "bulk
lane": `daemon.py --run-task <name>`, `Task.spawn_background`/`poll_background`).** The
loop's 60 s survival beats (oauth-rotator-tick above all) therefore never block behind a
bulk run. Stamps land at REAP time; `_BULK_RECHECK_SEC=5` bounds reap latency; a task with
a live child is never due; `Task.run()` skips while its own child is in flight (guards the
version-update consume fast-path).

**Why:** 2026-07-17 incident — marketplace-refresh ran ~1190 s at low priority with a
1200 s cadence (≈50% duty cycle, back-to-back runs); a 5 h wall landed inside a 20-min
blind window and rotation never fired; the user switched accounts by hand. Diagnostic
signature: task `.last-run.ts` stamps frozen while `daemon.heartbeat.ts` stays fresh.

**Cadence rule:** never set a task cadence ≈ its worst-case runtime (stamp-at-completion
makes it due again immediately). marketplace-refresh default is now 3600 s.

## See also

- [[janitor-per-project-channeling]] — the other v0.50.0 invariant
- [[janitor-daemon-handover-unowned-chores]] — the OTHER cause of stale chore
  stamps: the daemon is not blocked, it is deliberately absent because a live
  ai-maestro server owns the host. Same symptom, opposite cause.
- TRDD-H7NVKSAX (incident + fix), TRDD-FQXBURNR (burn-rate-aware rotation, open)

## Notes and lessons learned

[^1]: [id:ATOM-BLKL-TEST, status:valid, keywords:"monkeypatch CLAUDE_PROJECT_DIR ignored flaky order dependent test wrote into real repo janitor state seen file lru_cache project_root", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT assume a monkeypatched CLAUDE_PROJECT_DIR isolates janitor state in tests,
  BECAUSE state.project_root/janitor_root/state_dir/log_dir are lru-cached process-wide —
  the FIRST resolver wins and later tests silently read/write the REAL repo's .janitor/
  (an hour-keyed seen-file there muted a watchdog test). DO cache_clear all four in the
  isolation fixture (pattern: test_daemon.py::_isolate_project_paths).
