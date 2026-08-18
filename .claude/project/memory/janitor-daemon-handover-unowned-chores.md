---
name: janitor-daemon-handover-unowned-chores
description: "every daemon chore stamp is frozen at the same age but no flag is set / daemon.pid is MISSING and nothing respawns it / recent_spawn_count is 0 while the heartbeat fires every 5 minutes / ensure_daemon_running silently does nothing / no rotation no cache prune no memory guard no session-liveness watchdog / who runs the chores the ai-maestro server never absorbed / is the daemon dead or deliberately absent / plugin stuck four releases behind and the daemon is gone / daemon.heartbeat.ts is hours stale and the spawn-attempt stamp is days old / the daemon starts and then exits after about one second / daemon.log says stopping server-owns-host / os-keepalive activate then uninstall on every spawn / should I force the janitor daemon back up"
ocd: 2026-07-29
lmd: 2026-08-18
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: daemon-ownership
publish-globally: false
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


^ATOM-KYRU-GT5O [desc: "Rev-8 contract: executor-declared staleness bounds (claim-bounds.json, widen-only, fail-open); github-config-audit joined the absorbed set", keywords: claimed_chore_stale_false_alarm server_cadence_differs_from_janitor_roster claim-bounds.json widen-only_declared_bound github-config-audit_yields_to_server absorbed_set_changed rev_8_contract chore_stamp_bound_table, type: project, ocd: 2026-08-18, lmd: 2026-08-18]

Ratified 2026-08-18 (both sessions under the USER's delegation; janitor ARCHITECTURE.md §9 rev 8; server mirror docs/claimed-chores-contract.md @ eccbd02a; thread ai-maestro#126). The claimed-chore watchdog no longer trusts only the JANITOR roster cadence for a chore the SERVER executes: the executor declares its own bound in ~/.claude/janitor-control/claim-bounds.json and claimed-chore-stale reads it FAIL-OPEN, with widen-only enforcement in claimed_chore_watch.stale_threshold — a declaration can only RAISE a bound, because honouring a narrower one would let the other side's config manufacture false positives (janitor#225 mirrored). Same round: github-config-audit JOINED SERVER_ABSORBED_TASKS (janitor#274 — the server has stamped it since 2026-08-05), so it is class-2 absorbed, no longer class-4 janitor-internal; its declared 14400s bound is below the 64800s roster default and widen-only deliberately ignores it.

## Governed by

- [[janitor-architecture]] — the hub: the two tiers, the scope invariant, and why there is
  both a daemon and a heartbeat. This page is the ownership-handover case under it.

## See also

- [[janitor-fleet-control-plane]] — the flags and locks a second chore owner must observe;
  that page owns the coordination substrate, this one owns who executes.
- [[janitor-daemon-bulk-lane]] — the other way chore stamps go stale: the daemon is ALIVE
  but blocked behind a ~20 min bulk run. Same symptom, opposite cause.


^ATOM-FDNM-LHZ0 [desc:"the decisive tell for 'stood down' vs 'died' is the daemon's own 'stopping (server-owns-host)' log line — never the heartbeat gap, which looks identical either way", keywords: is_the_daemon_dead_or_deliberately_absent daemon_heartbeat_is_hours_stale_and_daemon_pid_is_gone spawn_attempt_stamp_is_a_week_old stopping_server_owns_host should_I_force_the_janitor_daemon_back_up daemon_starts_then_exits_after_one_second, type: project, ocd: 2026-08-01, lmd: 2026-08-01]

**The absence has two causes that look identical from state files, and one that tells them
apart.** `daemon.pid` missing + `daemon.heartbeat.ts` hours stale + `daemon.spawn-attempt.ts`
days old is EXACTLY what a crashed, un-respawned daemon looks like — and exactly what a
correct stand-down looks like too. Neither the gap nor the stamps can distinguish them,
because a daemon that exits deliberately stops writing precisely as one that died does.

**Read `<global-state>/daemon.log` and look for the daemon's own exit reason.** A stand-down
prints, within about a second of each start:

```
started (pid=…, tasks=[…])
os-keepalive activate: ok=True
os-keepalive uninstall: ok=True
stopping (server-owns-host)
```

That sequence — start, install the OS keepalive, immediately uninstall it, exit — IS the
withdrawal handshake, and it repeats on every spawn. A crash leaves no `stopping` line at
all; a kill-switch stop names the kill-switch instead. [^3]


^ATOM-N7UC-RFOR [desc:"once the withdrawal handshake is confirmed, corroborate against server-liveness and then do NOT force a daemon up — the defect to escalate is server-side", keywords: should_I_restart_the_janitor_daemon_myself server_liveness_json_staleness_window the_withdrawal_was_not_justified is_this_a_janitor_bug_or_a_server_bug escalate_the_absorbed_chore_that_never_runs, type: project, ocd: 2026-08-01, lmd: 2026-08-01]

**Corroborate from the other side before acting.** `~/.aimaestro/server-liveness.json` with a
beat inside its ~90 s staleness window means a live server owns the host — the condition that
legitimately produces the stand-down. Absent, stale, or malformed ⇒ the withdrawal was NOT
justified and the absence IS a real defect worth chasing.

**When the handshake and a fresh beat both check out, do not force a daemon back up.** The
janitor is obeying the binary coordination rule (TRDD-LU0C5KAR); overriding it re-creates the
two-owner collision that rule exists to remove, and a `flock` the other owner cannot see
excludes nobody. The thing to escalate is the server not EXECUTING what it absorbed — this
repo's contract is explicit that a running server which does not run an absorbed chore is a
server bug, never a janitor guard.


^ATOM-E3NC-H279 [desc:"Chore coordination Phase B2 — a fresh server-liveness.json probe file decides whether absorbed chores yield or the janitor runs them ALL", keywords: chore_coordination_phase_b2 server_liveness_json_probe server_is_alive_server_runs_chores binary_chore_switch_trdd_lu0c5kar capabilities_informational_field, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

- **Chore coordination (Phase B2, BINARY since TRDD-LU0C5KAR — owner directive
  2026-07-17):** responsibility follows server LIVENESS. A fresh auth-free probe file
  `~/.aimaestro/server-liveness.json` (`{ts,pid,capabilities}`, 30 s beat / 90 s
  staleness) ⇒ the server is RUNNING ⇒ ALL absorbed chores
  (`harness_backend.SERVER_ABSORBED_TASKS`: the OAuth pair + the update trio) yield;
  absent/stale/malformed ⇒ the janitor runs them ALL. `server_is_alive()` /
  `server_runs_chores()` are the switch (env overrides `JANITOR_AIMAESTRO_SERVER_CHORES`
  / `_STATE` first); the `capabilities` content is informational — "a running server
  that does not execute an absorbed chore is a server bug, never a janitor guard" (the
  rev-3 per-class token gating, TRDD-N9YAH5E7, is retired). File locks remain the
  collision backstop across the 90 s handoff window. `design/ARCHITECTURE.md` rev 4
  (proposed on janitor#100) is the canonical contract doc.


^ATOM-2VMQ-2U7X [desc:"The FIX for the all-or-nothing handover: a chore is the server's only when it is CLAIMED, and the daemon is suppressed only once EVERY chore is claimed", keywords: claim_gate alive_and_claimed server_owns_every_chore claimed_chores per-chore_capability_token daemon_suppressed_by_live_server chore_handover_incremental, ocd: 2026-08-05, lmd: 2026-08-05]

Owner ruling 2026-08-05 (janitor#134, "does the server's responsibility mean ALIVE or CLAIMED?"):
**it means BOTH**, and all chores must eventually pass to ai-maestro equivalents. This SUPERSEDES
the 2026-07-17 binary-on-liveness rule, which was right about direction and wrong about
granularity.

Shipped as `d45a843a`:

- `harness_backend.claimed_chores()` — the chores a live server has actually claimed. `family-a`
  maps to the five family-A chores; a capability token equal to a CHORE NAME claims that chore, so
  the server migrates one at a time with no janitor release per chore.
- `server_owns_every_chore()` now guards daemon suppression in
  `global_state.ensure_daemon_running` — previously `server_is_alive()`. A live server suppresses
  the daemon ONLY once it has claimed all eleven; while even one is unclaimed the daemon keeps
  looping and runs exactly the unclaimed remainder. That is the per-chore handover whose absence
  made the arithmetic never balance.
- No two-owner hazard in the gap: the daemon yields each claimed chore individually, so daemon and
  server never execute the same chore; the cross-process locks stay as the backstop.

Everything fails TOWARD COVERAGE: an empty capability list, an unrecognised token, or a stale probe
all claim nothing, so the janitor keeps every chore. A chore run twice is wasteful and lock-guarded;
a chore run by nobody is invisible. [^4] [^5]

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
[^3]: [id:ATOM-6CGH-BVIR, status:valid, desc:"I raised a false alarm from three agreeing state files and retracted it after reading the log", keywords:"concluded_the_daemon_was_dead_when_it_had_stood_down almost_force_spawned_a_daemon_the_server_owned three_state_files_agreed_and_all_three_were_the_wrong_evidence the_log_had_the_answer_the_whole_time", ocd:2026-08-01, lmd:2026-08-01] DO NOT conclude the daemon died from state files alone — not from a missing `daemon.pid`, a 21 h-stale `daemon.heartbeat.ts`, and a week-old `daemon.spawn-attempt.ts` together — BECAUSE all three are ALSO produced by a correct stand-down, so their agreement adds confidence without adding information, and their combined weight is what makes the wrong conclusion feel verified. I announced "the daemon has been dead for 21.6 h with no respawn attempt in a week" and was one step from force-spawning a daemon the ai-maestro server already owned, which is exactly the two-owner collision TRDD-LU0C5KAR exists to prevent. DO open `daemon.log` and read the daemon's OWN exit reason before diagnosing its absence: `stopping (server-owns-host)`, repeating once per spawn, settles it in one line.
[^4]: [id:ATOM-XGE0-4WI4, status:valid, desc:"the mirror hole an unabsorbed-only detector cannot see", keywords:"ownerless_chore_two_shapes claimed_with_no_live_server operator_override_yields_into_nothing detector_gate_hid_the_hole who_will_run_this", ocd:2026-08-05, lmd:2026-08-05] DO NOT detect ownerless chores by asking "which chores were never absorbed", BECAUSE that is only ONE of the two ways a chore ends up with no runner — the mirror case is a chore that IS claimed while no live server exists, reachable through the operator override, which asserts "the server runs chores" with no probe to corroborate it and makes the daemon yield all five absorbed chores to a server that is not there; my detector stayed silent through it, and its own gate returned early whenever the daemon was alive, so the hole was skipped before it was ever computed (the daemon can be alive AND yielding into nothing). DO ask, per chore, "who will run this?" — claimed with no live server, or unclaimed with no daemon — which catches both shapes by construction.
[^5]: [id:ATOM-LXHT-XUB9, status:valid, desc:"the corpus already held this on 2026-08-01; four days later I re-derived it from scratch", keywords:"recall_before_acting rediscovered_known_defect memory_not_consulted wasted_window corpus_already_knew", ocd:2026-08-05, lmd:2026-08-05] DO NOT begin a multi-hour investigation into janitor/server chore coverage without running `memgrep recall` first, BECAUSE this exact defect was already recorded on this page on 2026-08-01 — including lesson [2], "enumerate the FULL set the withdrawn actor owned and subtract what the new owner claims" — and on 2026-08-05 I re-derived all of it from scratch across dozens of turns, measuring stamps and reading source the corpus had already summarised, on a token window the owner was actively watching burn. The knowledge was not missing; the lookup was. DO recall on the SYMPTOM ("chore not running", "daemon absent", "stamps frozen") before the first measurement, and treat a hit as the starting point rather than a confirmation to be earned.
