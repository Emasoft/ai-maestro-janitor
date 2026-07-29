---
name: janitor-fleet-control-plane
description: "a chore ran twice / two daemons / the ai-maestro server ignored maintenance mode and kept running chores / a flag I set had no effect on the other daemon / where do the kill-switch and maintenance flags actually live / why is there a ~/.claude/janitor-control folder when the rule says use the DATA dir / a lock stopped excluding anything after I moved it / a chore skips forever but the logs only say contended"
ocd: 2026-07-22
lmd: 2026-07-22
metadata:
  node_type: memory
  type: project
  tier: component
---

# The fleet control plane — `~/.claude/janitor-control/`

## Governed by

- [[janitor-architecture]] — the hub. This page owns ONE element of it: the
  externally-readable control directory and the migration of coordination state
  into it (ARCHITECTURE.md §7.1, TRDD-QK7M2B0X).

## What it is and why it breaks the DATA-dir principle

A **second chore owner** exists on the host: an ai-maestro server absorbs the
OAuth pair and the update trio (`harness_backend.SERVER_ABSORBED_TASKS`). Two
owners can only coordinate through state BOTH can find.

`global_state_dir()` resolves through a four-rung ladder (env override → XDG →
plugin DATA → legacy). A foreign program can hardcode exactly one rung, and on
any host where a different rung applies it stats a file that never exists —
which reads as **"flag absent"**, i.e. it ignores the control plane while
looking perfectly healthy. A control plane whose miss-mode is "looks fine" is
worse than none.

So the control plane is a **literal, unresolved path**: `~/.claude/janitor-control/`
(`$JANITOR_CONTROL_DIR` overrides it for TESTS ONLY). This is the one sanctioned
exception to "prefer `${CLAUDE_PLUGIN_DATA}`" — and it is not a reversal of that
principle, it is its consequence. The DATA dir's virtues (survives updates,
backed up) are exactly the properties a mode flag must NOT have: an uninstalled
janitor must not leave a flag behind claiming the host is in maintenance.

## The scope rule is AUDIENCE, not kind

> If a SECOND chore owner must observe it or contend on it, it moves.

| in `~/.claude/janitor-control/` | stays in `<DATA>/global-state/` |
|---|---|
| the six MODE flags (kill-switch, maintenance, global-pause, the two reload generations, version-update-request) | `recovery-audit.ndjson`, token-attribution cache, `migrated-from-legacy.ts`, fleet injection stamps, `daemon.spawn-attempt.ts` |
| the three COORDINATION locks: `marketplace-op`, `oauth-rotator-tick`, `settings-ensurer` | `ticket-dispatch.lock` — janitor-internal, no second owner ever dispatches a janitor ticket |
| the per-chore `*.last-run.ts` stamps | |
| the daemon singleton: `daemon.pid`, `daemon.flock`, `daemon.heartbeat.ts` | |

Flags carry provenance (`{set_at, by, pid, reason}`) but **readers key on
PRESENCE only** — a corrupt body must never swallow a stop signal.

## Migration status

- **Phase A** (v0.60.0) — the six mode flags. Triple-read on read (new + old +
  legacy), single-write on write, clear sweeps all three.
- **Phase B step 1** (`78879d4`) — the three coordination locks.
- **Phase B step 2** — `*.last-run.ts` stamps, then **separately and last** the
  singleton under flock-moves-LAST. NOT done.

## Moving a LOCK is not moving a FLAG — dual-LOCK, not dual-READ

This is the load-bearing distinction of the whole migration.

A flag is **data**: a reader that probes both paths cannot miss it, so a
dual-READ is a complete transition. A flock is **kernel state bound to an
inode**: during the upgrade window a new-code peer locking only the new path and
an old-code peer locking only the old one BOTH acquire and both run the chore.
That is not a missed signal — it is the concurrent `claude plugin marketplace
update` that issue #7 exists to prevent.

`_acquire_dual_flock` therefore holds **both inodes** for one critical section,
order fixed NEW-then-OLD (uniform order + non-blocking ⇒ deadlock-free),
releasing the half it took when the other is contended. `acquire_*_lock()`
returns an **opaque handle**, never a bare fd. Retire the OLD half two releases
out and the tuple collapses back to one fd.

The singleton move **cannot reuse this primitive**: it must hold the NEW lock
ACROSS the retirement of the OLD one, whereas `_acquire_dual_flock` releases
both halves on partial failure.

## See also

- [[janitor-daemon-handover-unowned-chores]] — this page owns the coordination
  SUBSTRATE (which flags and locks a second chore owner must observe); that one
  owns who actually EXECUTES, and what stops running when the janitor hands the
  whole host to a live ai-maestro server.

## Notes and lessons learned

[^1]: [id:ATOM-QK7M-0002, status:valid, keywords:"lock_moved_to_new_path dual_lock_self_deadlock same_inode_opened_twice chore_skips_forever flock_across_open_descriptions", ocd:2026-07-22, lmd:2026-07-22]
  DO NOT hold a migrating lock at BOTH its old and new path without first
  checking they are the same file, BECAUSE flock(2) conflicts across independent
  open file descriptions even inside ONE process, so when the two dirs coincide
  the second open denies you your own lock and the chore skips FOREVER while
  logging as ordinary contention. DO compare `os.path.realpath` of both paths and
  lock a single inode once.

[^2]: [id:ATOM-QK7M-0001, status:valid, keywords:"external_consumer_hardcodes_path resolution_ladder_silent_miss XDG_STATE_HOME_moves_dir flag_read_returns_false", ocd:2026-07-21, lmd:2026-07-21]
  DO NOT publish a cross-process contract on a path that resolves through a
  ladder, BECAUSE a foreign reader can only hardcode one rung and every other
  rung then makes it read a file that does not exist — which returns "flag
  absent", i.e. it silently ignores the control plane instead of failing loudly.
  DO give an external contract a literal fixed path, and keep ladder-resolved
  locations for state only this plugin reads.

[^3]: [id:ATOM-QK7M-0003, status:valid, keywords:"integration_test_caught_what_unit_tests_missed harness_pinned_both_env_vars_same_dir coincident_paths", ocd:2026-07-22, lmd:2026-07-22]
  DO NOT trust a path-migration's unit tests to cover the degenerate case where
  the old and new locations RESOLVE TO THE SAME PLACE, BECAUSE every unit test
  points them at two distinct tmp dirs while a real harness (or a user config)
  may legitimately pin both at one — here the daemon integration harness sets
  `JANITOR_CONTROL_DIR` = `JANITOR_GLOBAL_STATE_DIR` and was the ONLY thing that
  caught it. DO add an explicit coincident-paths test when a path moves.
