---
name: janitor-fleet-control-plane
description: "a chore ran twice / two daemons / the ai-maestro server ignored maintenance mode and kept running chores / a flag I set had no effect on the other daemon / where do the kill-switch and maintenance flags actually live / why is there a ~/.claude/janitor-control folder when the rule says use the DATA dir / a lock stopped excluding anything after I moved it / a chore skips forever but the logs only say contended / what is the audience scope rule for the control plane / why does JANITOR_CONTROL_DIR only apply to tests / flock conflicts across independent open file descriptions even in one process / dual flock new-then-old order deadlock free / external consumer hardcoded one rung of the resolution ladder and silently missed the flag / does moving a lock differ from moving a flag / integration test caught coincident JANITOR_CONTROL_DIR and JANITOR_GLOBAL_STATE_DIR paths"
ocd: 2026-07-22
lmd: 2026-09-02
metadata:
  node_type: memory
  type: project
  tier: component
publish-globally: false
---

# The fleet control plane — `~/.claude/janitor-control/`

## Governed by

- [[janitor-architecture]] — the hub. This page owns ONE element of it: the
  externally-readable control directory and the migration of coordination state
  into it (ARCHITECTURE.md §7.1, TRDD-QK7M2B0X).

## What it is and why it breaks the DATA-dir principle

^8ZFF42S7 [desc:"A second chore owner (an ai-maestro server) can also run janitor chores, so the control plane must be a literal unresolved path (~/.claude/janitor-control/), not a ladder-resolved DATA-dir flag a foreign reader could silently miss.", keywords:"second_chore_owner_ai_maestro_server global_state_dir_four_rung_ladder foreign_program_hardcodes_one_rung flag_absent_looks_healthy literal_unresolved_control_path janitor_control_dir_tests_only data_dir_survives_updates_wrong_for_mode_flags uninstalled_janitor_must_not_leave_flag"]
A **second chore owner** exists on the host: an ai-maestro server absorbs the
OAuth pair and the update trio (`harness_backend.SERVER_ABSORBED_TASKS`). Two
owners can only coordinate through state BOTH can find.

`global_state_dir()` resolves through a four-rung ladder (env override → XDG →
plugin DATA → legacy). A foreign program can hardcode exactly one rung, and on
any host where a different rung applies it stats a file that never exists —
which reads as **"flag absent"**, i.e. it ignores the control plane while
looking perfectly healthy. A control plane whose miss-mode is "looks fine" is
worse than none. [^2]

So the control plane is a **literal, unresolved path**: `~/.claude/janitor-control/`
(`$JANITOR_CONTROL_DIR` overrides it for TESTS ONLY). This is the one sanctioned
exception to "prefer `${CLAUDE_PLUGIN_DATA}`" — and it is not a reversal of that
principle, it is its consequence. The DATA dir's virtues (survives updates,
backed up) are exactly the properties a mode flag must NOT have: an uninstalled
janitor must not leave a flag behind claiming the host is in maintenance.

## The scope rule is AUDIENCE, not kind

^I8XY42BG [desc:"The control-plane scope rule is AUDIENCE not kind: if a second chore owner must observe or contend on a piece of state, it moves to janitor-control/; mode flags and the three coordination locks move, janitor-internal-only state stays in DATA/global-state.", keywords:"scope_rule_is_audience_not_kind second_owner_must_observe_or_contend six_mode_flags_move three_coordination_locks_move per_chore_last_run_stamps daemon_singleton_pid_flock_heartbeat ticket_dispatch_lock_stays_janitor_internal flags_carry_provenance_but_key_on_presence_only"]
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

^0Y09UI3D [desc:"Migration to the control plane proceeds in phases: Phase A (six mode flags, triple-read/single-write) is done, Phase B step 1 (three coordination locks) is done, Phase B step 2 (last-run stamps + the flock-moves-last singleton) is NOT done.", keywords:"migration_phase_a_six_mode_flags_done phase_b_step_1_coordination_locks_done phase_b_step_2_not_done triple_read_new_old_legacy single_write_clear_sweeps_all_three last_run_stamps_pending daemon_singleton_flock_moves_last v0_60_0_release"]
- **Phase A** (v0.60.0) — the six mode flags. Triple-read on read (new + old +
  legacy), single-write on write, clear sweeps all three.
- **Phase B step 1** (`78879d4`) — the three coordination locks.
- **Phase B step 2** — `*.last-run.ts` stamps, then **separately and last** the
  singleton under flock-moves-LAST. NOT done.

## Moving a LOCK is not moving a FLAG — dual-LOCK, not dual-READ

This is the load-bearing distinction of the whole migration.

^IJX58BQ6 [desc:"Moving a LOCK is not moving a FLAG: a flag is data (dual-read is complete), but a flock is kernel state bound to an inode, so during migration two peers locking different paths BOTH run the chore; _acquire_dual_flock holds both inodes, order fixed NEW-then-OLD, deadlock-free.", keywords:"flag_is_data_dual_read_complete flock_is_kernel_state_bound_to_inode new_and_old_peer_both_run_chore acquire_dual_flock_holds_both_inodes order_fixed_new_then_old_deadlock_free release_half_when_other_contended opaque_handle_never_bare_fd singleton_move_cannot_reuse_this_primitive"]
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
out and the tuple collapses back to one fd. [^1]

The singleton move **cannot reuse this primitive**: it must hold the NEW lock
ACROSS the retirement of the OLD one, whereas `_acquire_dual_flock` releases
both halves on partial failure.

## See also

- [[janitor-daemon-handover-unowned-chores]] — this page owns the coordination
  SUBSTRATE (which flags and locks a second chore owner must observe); that one
  owns who actually EXECUTES, and what stops running when the janitor hands the
  whole host to a live ai-maestro server.
- [[janitor-has-no-off-switch-but-disarm]] — the opt-IN capability flags
  (`hard_restart_enabled`, `fleet_stop_enabled`, `issues-watch`) that live in this
  control plane and ARM extra capability rather than disable existing work.
- [[janitor-daemon-process-identity]] — which interpreter the daemon runs under (the TCC-grantable identity), the restart gate that evicted our own version-less daemons, and the breaker that quarantined a healthy version for it.

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
