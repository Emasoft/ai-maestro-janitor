---
trdd-id: BEXY5KIP
title: Dispatcher consumes the server-published plugins-updated signal so server-lane sweeps still surface a reload
column: testing
created: 2026-08-20T00:53:21+0200
updated: 2026-08-20T08:05:00+0200
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

## SHIPPED 2026-08-20 08:05 (`todo → testing`) — simpler than carded: one more source in the max

The card sketched a separate consumed-stamp in our state dir. Superseded during
implementation: `reload_generation()` is ALREADY a max over several stamp locations, and
`_phase_plugin_reload`'s per-project `reload-acked.ts` IS the consumption record — so the
server signal became one more READ-ONLY source in that max
(`_server_plugins_updated_epoch`), with zero new state and the entire existing phase
(per-project ack, reload-churn guard, marker emission) inherited unchanged.

FAIL-OPEN toward 0 on every producer defect (absent/unreadable/malformed/wrong-shape/
non-positive). ONE guard fails the other way and is the non-obvious part: an epoch more
than a day in the FUTURE is IGNORED, because the phase advances each project's ack TO the
generation — a bogus huge epoch would ratchet every ack past all future real generations
and silently disable reload signalling machine-wide, forever.

## Acceptance

- [x] server-lane sweep surfaces `[janitor-reload]` in sessions with no janitor-side flag
      write (the signal feeds the generation the existing phase already consumes)
- [x] boundary preserved both ways — pinned: N reads leave the producer's file byte-identical
- [x] pytest (15611 green, full suite), ruff, mypy, pyright clean; 11 tests incl. the
      newer-source-wins-either-way pair and the far-future ratchet guard

Gate to `complete`: one live observation — a hub sweep publishes, a janitor session with no
local flag emits `[janitor-reload]` once and stays silent after. Needs 3.3.19 cached.

## Approval log
