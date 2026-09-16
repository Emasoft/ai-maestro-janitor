---
trdd-id: E39YT9G6
title: Retire user-plugins-update from GLOBAL_CHORES — the daemon-side fleet sweep is superseded by the server lane
column: complete
created: 2026-08-19T20:15:22+0200
updated: 2026-08-21T02:40:00+0200
current-owner: janitor-main-session
task-type: refactor
priority: normal
approval-tier: 0
scope: project
external-refs: [TRDD-TIZHEPNC, TRDD-4OFMHOZ7]
npt: []
eht: []
---

# Retire user-plugins-update from GLOBAL_CHORES (3.3.18, committed to the hub peer)

## Why

Design answer given to the ai-maestro hub on 2026-08-19 (absorption thread, follows
TRDD-TIZHEPNC which already removed it from SERVER_ABSORBED_TASKS). PREMISE, stated
precisely (the first draft of this card said "the server lane owns it" — WRONG: the server
DELETED its own loop in PE54D95Q AC6): **the HARNESS owns plugin self-updates** —
`autoUpdate:true` refreshed catalogs upgrade installed plugins with no janitor and no
server involved (measured 261/261; this repo rolled 3.3.15→3.3.16 with the server down).
So the sweep should exist NOWHERE — the server already dropped its copy; this card drops
the daemon's. The 2026-08-19 incident record (TRDD-4OFMHOZ7) shows what the daemon-side
sweep costs under load: serial spawns each timing out, a 2184 s child killed by the
workload cap (rc=-9), on a host already at memory pressure — all duplicating work the
harness does anyway.

## Measured consumer inventory (recon 2026-08-19 20:29 — the sweep list below is grounded in this)

Scripts naming the chore: `daemon.py` (Task row :2185, `task_user_plugins_update` ~:460-520,
requests-consumer gate :2737 — KEEP the consumer), `lib/harness_backend.py` (GLOBAL_CHORES),
`lib/claimed_chore_watch.py` (historical comment), `lib/daemon_watchdog.py`,
`lib/fleet_plugin_updates.py`, `dispatch.py`, `identify_environment.py`,
`detectors/user-plugins-update.py`, `detectors/local-plugins-update.py`,
`detectors/global-chore-blackout.py`, `detectors/marketplace-refresh.py` (its comment says
its only consumer is this chore — decide marketplace-refresh's fate explicitly, do not
orphan it silently). Tests: test_control_dir_flags, test_claimed_chore_watch,
test_chore_coordination, test_daemon_bulk_lane, test_daemon_integration,
test_harness_exclusion, test_daemon_fleet_plugins_update, test_user_plugins_update_stale,
test_global_chore_blackout. ~15+ files ⇒ run as PHASED work (≤5 files/phase, verify
between), not a single pass.

## What (sweep — every consumer, per check-all-files-after-breaking-change)

1. Remove the `user-plugins-update` Task registration + its `task_*` fn from
   `scripts/daemon.py` and its row from the GLOBAL_CHORES registry
   (`scripts/lib/harness_backend.py`).
2. **KEEP `_consume_plugin_update_requests`** — the targeted per-plugin request consumer
   is not the sweep and stays.
3. Delete/retire `scripts/detectors/user-plugins-update.py` if it exists as a detector
   surface; sweep ALL references: tests (test_chore_coordination, test_global_chore_blackout
   pins), docs, memory pages (janitor-beat-tasks-and-limitations, janitor-fleet-control-plane),
   rules-reference, skills.
4. Bump-time note in CHANGELOG: the chore is retired, not absorbed — the HARNESS
   self-updates plugins; neither daemon nor server runs a sweep.

## Acceptance

- [x] no `user-plugins-update` Task in the daemon roster; requests-consumer intact (gate
      ungated — dead condition removed) + tested (test_universal_plugin_autoupdate pins the
      fleet/self guards; test_daemon_integration reload-flag pair repointed to the consumer;
      NEW retirement pin: the daemon must never spawn an unrequested `plugin update`)
- [x] full-repo grep shows only deliberately-historical mentions (scripts, tests, README,
      ARCHITECTURE, 6 memory pages; detector + its test git-rm'd, recoverable from history)
- [x] pytest (15597 green, full suite), ruff, mypy clean; chore-coordination + blackout +
      bulk-lane + harness-exclusion pins updated (the unabsorbed pin is seven now)
- [x] memory pages updated: lesson ATOM-GLM6-PIK9 (WHY, on the owning beat-tasks page) via
      add-lesson; 5 pages' liveness claims corrected, all validate+lint clean, reindexed

SHIPPED 2026-08-20 01:37 (`todo → testing`). Gate to `complete`: rides the next publish
(3.3.19); then one daemon restart observed with the trimmed roster (12 GLOBAL_CHORES,
no user-plugins-update stamp advancing, requests-consumer still draining).

## Verified on the installed runtime — 2026-08-21, `testing` → `complete`

Resolved by IMPORT, not by grep, because a grep could not tell the retirement comment from a
live entry — `"user-plugins-update"` still appears once in the installed
`harness_backend.py` (line 99, the comment recording this very card).

Importing the installed 3.3.26 module:

```
user-plugins-update in GLOBAL_CHORES:      False
user-plugins-update in SERVER_ABSORBED_TASKS: False
roster size:                               13
```

13 matches the task count the running daemon logs at startup, so the roster the code exposes
and the roster the daemon actually runs agree.

## Approval log
