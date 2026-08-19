---
trdd-id: 9ZPU69UC
title: Cold-cache-clear via auto-rolling shell-out launcher so the server can fire it without importing janitor code
column: todo
created: 2026-08-19T20:15:22+0200
updated: 2026-08-19T20:15:22+0200
current-owner: janitor-main-session
task-type: feature
priority: normal
approval-tier: 0
scope: project
external-refs: [TRDD-TIZHEPNC]
npt: []
eht: []
---

# Cold-cache-clear launcher for the server lane (3.3.18, committed to the hub peer)

## Why

Absorption design answer to the hub (2026-08-19): when the ai-maestro server absorbs the
cold-cache-clear chore, it must NOT import or vendor janitor code — version skew between a
vendored copy and the shipped plugin is exactly the drift class the dispatcher-stub pattern
was built to kill. The server should shell out to a tiny AUTO-ROLLING launcher in the
janitor's DATA dir (same pattern as `dispatcher-stub.py`): the launcher re-resolves the
newest cached plugin version on every invocation and execs that version's
`task_cold_cache_clear` entry point, so plugin updates roll forward with no server-side
change. Logic stays in this repo; the launcher is a stable ABI.

## What

1. New `scripts/cold_cache_clear_launcher.py` staged into the DATA dir alongside
   `dispatcher-stub.py` (same install path in `arm_prepare.py` / the staging closure);
   resolves newest cached version, execs its cold-cache-clear entry (extract the daemon's
   `task_cold_cache_clear` body into an importable/runnable module first so the launcher
   does not import `daemon.py` wholesale).
2. Same safety gates as the daemon task keep living in the LOGIC, not the launcher:
   `external_clear.enabled()` opt-in, transcript-advancing skip, cooldown, one-per-invocation.
3. Guard against DOUBLE ownership: while the daemon still registers the chore, the
   beat-keyed yield (`claimed_chores()`) must cover it so server + daemon never both fire
   in one window.
4. Tell the hub the launcher path + contract when it ships.

## Acceptance

- [ ] launcher exists in the staged closure, auto-rolls (proven by a test faking two cached versions)
- [ ] no janitor import in the launcher beyond the resolver; server contract = argv only
- [ ] double-ownership window covered by chore-coordination; test pinned
- [ ] pytest, ruff, mypy clean; peer notified with path + contract

## Approval log
