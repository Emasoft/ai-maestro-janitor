---
name: janitor-daemon-handover-unowned-chores
description: "every daemon chore stamp is frozen at the same age but no flag is set / daemon.pid is MISSING and nothing respawns it / recent_spawn_count is 0 while the heartbeat fires every 5 minutes / ensure_daemon_running silently does nothing / no rotation no cache prune no memory guard no session-liveness watchdog / who runs the chores the ai-maestro server never absorbed / is the daemon dead or deliberately absent / plugin stuck four releases behind and the daemon is gone"
ocd: 2026-07-29
lmd: 2026-07-29
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: daemon-ownership
---

^one-daemon-per-host-withdraws-the-whole-daemon [desc: "a live ai-maestro server makes the janitor withdraw its ENTIRE daemon, not just the absorbed chores", keywords: all_chore_stamps_frozen_at_the_same_age daemon_pid_missing_but_no_kill_switch recent_spawn_count_zero_while_heartbeat_fires ensure_daemon_running_returns_without_spawning server_owns_host_guard one_daemon_per_host, type: project, ocd: 2026-07-29, lmd: 2026-07-29]
When a live ai-maestro server is on the host, `ensure_daemon_running()` refuses to spawn
the standalone daemon — third guard, `_server_owns_host()` (TRDD-5ZVS1DDP,
`ARCHITECTURE.md` §7.2, ONE DAEMON PER HOST). The refusal is correct in isolation: without
it, the daemon that just exited for that reason would be resurrected by the very next
heartbeat fire and the two-owner condition (concurrent writers on one state dir, chores run
twice) would return within seconds.

**But the janitor does not yield the absorbed chores — it withdraws the daemon that hosts
ALL of them.** So the SIX chores nobody ever absorbed stop too, and nothing anywhere says
so.[^1]

**Why:** Signature — every daemon `*.last-run.ts` frozen at the SAME age, with
`daemon.pid` MISSING, `daemon.heartbeat.ts` stale, **no** kill-switch / maintenance / pause
flag set, `crash_loop_active` False, and `recent_spawn_count(3600) == 0` even though the
heartbeat fires 12×/h. Zero spawn attempts with no breaker tripped is the tell: the guard
returns before recording an attempt, so there is no trace to read.

**How to apply:** Do not diagnose this as a dead or crash-looping daemon. Check
`harness_backend.server_is_alive()` FIRST — if a server is up, the daemon is *deliberately*
absent and no amount of restarting will help. Then ask the only question that matters:
**which chores does the server actually EXECUTE**, versus having absorbed on paper
(`SERVER_ABSORBED_TASKS`)? The gap is the difference.

^absorbed-set-is-narrower-than-the-daemon [desc: "six daemon chores are in no absorbed set and belong to nobody while the server owns the host", keywords: session_liveness_watchdog_down_for_days memory_guard_and_cache_prune_stopped fleet_stop_never_actuates who_owns_the_chores_the_server_did_not_absorb unowned_chore_gap, type: project, ocd: 2026-07-29, lmd: 2026-07-29]
`SERVER_ABSORBED_TASKS` holds the OAuth pair plus the update trio — **five** of the
daemon's eleven chores. The other six are in no absorbed set, are not gated by the server's
auto-update master toggle, and are assigned to the server by no design on either side:

`session-liveness` · `fleet-stop` · `memory-guard` · `cache-prune` · `rules-cleanup` ·
`github-config-audit`

They simply stop, because their host process is not permitted to exist. **`session-liveness`
is the one that matters most**: it is the watchdog that unwedges a frozen unattended
session, so its absence is invisible precisely until the moment it is needed.

**Why:** a stale janitor stamp for an ABSORBED chore is expected and healthy — it means the
server is doing the work and the janitor's stamp will never move again. The same stale stamp
for a NON-absorbed chore means nobody is doing it. The two look identical on disk.[^2]

**How to apply:** when reading frozen stamps, split the list by `SERVER_ABSORBED_TASKS`
membership before drawing any conclusion. Tracked as ai-maestro#103 (the running-state
question) and as the open scope decision on TRDD-5ZVS1DDP: either §7.2 stops being
all-or-nothing (daemon lives, yields only claimed chores), or the remaining six are absorbed
deliberately and advertised in `capabilities`.

## Governed by

- [[janitor-architecture]] — the hub: the two tiers, the scope invariant, and why there is
  both a daemon and a heartbeat. This page is the ownership-handover case under it.

## See also

- [[janitor-fleet-control-plane]] — the flags and locks a second chore owner must observe;
  that page owns the coordination substrate, this one owns who executes.
- [[janitor-daemon-bulk-lane]] — the other way chore stamps go stale: the daemon is ALIVE
  but blocked behind a ~20 min bulk run. Same symptom, opposite cause.

## Notes and lessons learned

[^1]: [id:ATOM-JDHU-4A18, status:valid, keywords:"read_a_stale_chore_stamp_as_nothing_is_running janitor_stamp_only_moves_when_the_janitor_runs_it concluded_rotation_was_dead_when_the_server_was_doing_it last_switch_at_measures_switches_not_refreshes", ocd:2026-07-29, lmd:2026-07-29]
  DO NOT read a stale janitor `*.last-run.ts` as "this work is not happening", BECAUSE the
  stamp only moves when the JANITOR runs the chore, so for an ABSORBED chore a frozen stamp
  is exactly what correct server-side execution looks like — I concluded rotation was dead
  from a 94 h `oauth-rotator-tick` stamp plus `state.json::last_switch_at` at 192 h, while
  the server had in fact been refreshing every 60 s since the gate was armed
  (`last_switch_at` counts account SWITCHES, not keepalive refreshes). DO ask the other side
  what it EXECUTES before concluding anything from a stamp you own.

[^2]: [id:ATOM-JDHU-6C27, status:valid, keywords:"scoped_the_bug_to_the_absorbed_chores_and_missed_the_unabsorbed_ones filed_an_issue_narrower_than_the_actual_hole both_sides_correct_but_the_union_has_a_gap", ocd:2026-07-29, lmd:2026-07-29]
  DO NOT scope a handover defect to the chores that WERE handed over, BECAUSE the failure of
  an all-or-nothing handover lands hardest on the duties nobody transferred: this was filed
  as "one absorbed update chore is not running" when six never-absorbed chores — including
  the frozen-session watchdog — had been down just as long, with both sides behaving exactly
  as designed and only the union containing a hole. DO enumerate the FULL set the withdrawn
  actor owned and subtract what the new owner claims, rather than starting from the claim.
