---
trdd-id: KVS6K7P9
title: memory-maint-pending is a single slot — per-dispatch state plus a per-root in-flight gate
column: todo
created: 2026-08-08T12:01:18+0200
updated: 2026-08-08T12:01:18+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#242, janitor#238, janitor#140]
---

# memory-maint-pending: per-dispatch state + per-root in-flight gate

## Why (janitor#242, webdesign peer — measured)

`.janitor/state/memory-maint-pending.json` is the AUTHORITY a spawned memory agent must read
(heartbeat-protocol rule), but it is a single slot the next `[janitor-memory-*]` marker
overwrites unconditionally. Measured: a repair dispatch was clobbered by a consolidate marker
367 s later, SAME root, while `pending-agents.json` still listed the repair agent live and the
root still had 10 ERROR-level lint findings. Two live failure modes: (1) an in-flight agent
that re-reads its authority sees a DIFFERENT chore and can abandon half-finished work; (2) two
markers on one root put two editors on one knowledge store (the peer prevented both by hand —
nothing in the protocol asks for that).

## What (the peer's shape, adjusted to what already exists)

1. **Per-dispatch state**: `memory-maint-pending-<dispatchId>.json` (or a list file); the
   marker's PAYLOAD carries the dispatch id; the agent verifies id ↔ state and STOPS on
   mismatch (never switches chore mid-flight). The single-slot path is retired — heartbeat
   rule text updated in the same release.
2. **Per-root in-flight gate in the SCHEDULER** (`memory-maintenance.py`): before stamping a
   new pending for a root, check whether a live dispatch (pending-agents manifest entry that
   is a janitor memory agent + unexpired) already holds that root — if so DEFER (no marker
   this fire) rather than clobber. This is the missing scheduler-side half; the EXISTING
   `memory_txn.commit_lock` already serializes commits per scope root, so mode 2's
   lost-update is bounded at the txn layer today — the gate removes the wasted double
   pass-planning and the semantic interleave above the txn layer.
3. Stale-dispatch reclamation: a per-dispatch file older than the agent-liveness window is
   the ORPHANED case — TRDD-2112XCKO's detector consumes it (these two cards compose: 2112XCKO
   detects the never-consumed file; this card guarantees the file it reads is per-dispatch and
   trustworthy).
4. **The per-dispatch state carries SCOPE and ROOT, not just the chore** — added after a
   SECOND live reproduction on the janitor's own host (2026-08-11, 515 s apart): a
   `consolidate/USER` dispatch was clobbered by a `conflict/LOCAL` marker while the first
   agent was still running, so the clobber changed the CORPUS as well as the verb. Mode 2 did
   not bite only because the two roots differed — luck, not design.
5. **Reword the agent-facing contract**: the heartbeat-protocol rule currently says the
   pending file IS the authority, which is exactly what makes a conscientious agent RE-READ it
   mid-run and adopt a foreign assignment. It must say: *your (intervention, scope, root) were
   fixed at launch; the pending file is not a live authority to poll* — with the dispatch-id
   check (item 1) as the only sanctioned re-read, and STOP-on-mismatch as the only response.

## Acceptance

- [ ] Clobber scenario replayed: second marker on a held root DEFERS, first agent's authority
      file untouched
- [ ] Id-mismatch test: agent reading a state whose dispatch id differs STOPS with a report
- [ ] Heartbeat-protocol rule + memory skills updated to the per-dispatch contract in the
      same release (no half-migrated window)
- [ ] #242 answered when it ships (#140 noted — the deferred dispatch also prevents the
      third ~189k abstain recurrence pattern)
