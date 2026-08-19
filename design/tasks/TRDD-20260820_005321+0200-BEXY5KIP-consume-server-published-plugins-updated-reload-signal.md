---
trdd-id: BEXY5KIP
title: Dispatcher consumes the server-published plugins-updated signal so server-lane sweeps still surface a reload
column: todo
created: 2026-08-20T00:53:21+0200
updated: 2026-08-20T00:53:21+0200
current-owner: janitor-main-session
task-type: feature
priority: normal
approval-tier: 0
scope: project
external-refs: [ai-maestro TRDD-JBFM8XR0]
npt: []
eht: []
---

# Consume ~/.aimaestro/state/plugins-updated.json (contract named to the hub 2026-08-20 00:50)

## Why

The hub absorbed `fleet-plugins-update` (JBFM8XR0) but honours the publish/consume boundary:
it will NOT write our `reload-needed.flag`. So a server-lane sweep that updates plugins
leaves every session unaware a reload is due. Contract agreed by message: the server writes
`~/.aimaestro/state/plugins-updated.json` atomically (temp+rename) on each non-empty sweep —
`{"updated_at_epoch": <int>, "updated": ["<plugin>@<mkt>", ...], "by": "fleet-plugins-update",
"count": <int>}` — and the janitor consumes it read-only.

## What

1. Dispatcher (reload-marker phase): read the file (absent/malformed ⇒ silent no-op,
   fail-open); compare `updated_at_epoch` to a last-consumed stamp in the JANITOR state dir
   (never touch their file); newer ⇒ emit `[janitor-reload]` exactly like the existing
   flag path, then stamp consumed.
2. Per-session dedupe: the stamp is per-project state (each session surfaces once), same
   as reload-needed.flag semantics.
3. Tests: newer-epoch ⇒ marker once then stamped; unchanged ⇒ silent; malformed/absent ⇒
   silent; their file never written/deleted by us.

## Acceptance

- [ ] server-lane sweep surfaces `[janitor-reload]` in sessions with no janitor-side flag write
- [ ] boundary preserved both ways (no write into ~/.aimaestro from the consumer)
- [ ] pytest, ruff, mypy clean

## Approval log
