---
trdd-id: E39YT9G6
title: Retire user-plugins-update from GLOBAL_CHORES — the daemon-side fleet sweep is superseded by the server lane
column: todo
created: 2026-08-19T20:15:22+0200
updated: 2026-08-19T20:15:22+0200
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
TRDD-TIZHEPNC which already removed it from SERVER_ABSORBED_TASKS): the 77-plugin
`claude plugin update` sweep belongs to the server lane, not the janitor daemon. The
2026-08-19 incident record (TRDD-4OFMHOZ7) shows why the daemon-side sweep is a liability
under load: serial spawns each timing out, a 2184 s child killed by the workload cap
(rc=-9), all on a host already at memory pressure — while the hub runs the same chore in
its own lane. One owner, not two.

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
4. Bump-time note in CHANGELOG: the chore is retired, not absorbed — the server owns it.

## Acceptance

- [ ] no `user-plugins-update` Task in the daemon roster; requests-consumer intact + tested
- [ ] full-repo grep shows only deliberately-historical mentions
- [ ] pytest, ruff, mypy clean; chore-coordination + blackout pins updated
- [ ] memory pages updated via memgrep verbs (supersede, not overwrite)

## Approval log
