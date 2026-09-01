---
name: janitor-architecture-control-flow
description: "how does the janitor heartbeat vs daemon control flow work / what does dispatch.py do each fire / full/maintenance/stop heartbeat modes / what is the scope invariant / which ops go to the daemon vs per-session detectors / what does self-healing across respawn paths mean / does the C3 quarantine cover both the stub and the keepalive path / what is the janitor-renew marker for / does the janitor cron survive a claude restart / what is the SessionStart re-arm nudge / what is the two-tier architecture (verbatim historical)"
ocd: 2026-06-13
lmd: 2026-09-01
metadata:
  node_type: memory
  type: project
  tier: component
  globs:
    - "scripts/**"
publish-globally: false
split-lineage: 959060b8fb99469c8afe79d502cf3dac
---

# ai-maestro-janitor — control flow (heartbeat, daemon, scope invariant)

## The two tiers

**Tier 1 — per-session heartbeat (project scope).** A durable `CronCreate`,
one per project, fires a fresh turn roughly every 5 minutes. Each fire runs the
project-scoped detectors `--one-shot` and emits one-line "drift" findings to
the model. It is **silent when nothing drifts** — no findings means no output,
so it does not nag. Findings are deduped (seen-file + content-hash) so an
unchanged condition stays quiet across fires.

**Tier 2 — global singleton daemon (user/global scope).** Exactly ONE
machine-wide process owns the expensive, shared, user-scope commands so that N
concurrent sessions don't stampede the same command (this is the whole point of
issue #7). It is spawned lazily by whichever session's heartbeat first notices
it is dead, holds a singleton flock so a second copy exits immediately, and
auto-rolls to the latest plugin version on its own.

### Control flow — heartbeat

The cron prompt invokes the **auto-rolling dispatcher stub** (lives in the
persistent data dir), which re-resolves the latest cached `scripts/dispatch.py`
and `os.execv`s into it — so plugin updates roll forward with NO re-arm of the
cron. `dispatch.py` then, in order:

1. resume markers — if a rate-limit or post-compact resume flag is set, emit a
   `[janitor-resume]` line (optionally "…continue TRDD-xxxx…") and clear it;
2. renewal — if the cron is near its 7-day expiry, emit `[janitor-renew]` (the
   model re-runs `/janitor-arm`);
3. `ensure_daemon_running()` — lazy-spawn the singleton if it is dead;
4. daemon staleness/old-version — request a restart so the daemon auto-rolls
   too;
5. run each **due** detector `--one-shot`, emitting only NEW findings;
6. reload — if a reload flag is set, emit `[janitor-reload]` (the model runs
   `/reload-plugins`).

### Heartbeat modes — full / maintenance / stop (TRDD-FPL60EKV, v0.27.0)

`dispatch._resolve_heartbeat_mode()` picks one of three modes per fire:
**full** (the sequence above — due detectors + daemon spawn), **maintenance**
(refreshes the prompt cache at the 0.1× cache-read rate and does NOTHING
else — no detectors, no daemon spawn, no output — vs. letting the cache die
and paying the 1.0× rewrite rate on the next real turn, a ~10× difference),
or **stop** (self-disarm: emits `[janitor-self-disarm]`, the model runs
`/janitor-disarm`, the cron deletes itself). Maintenance WINS over a global
stop — one session can stay cache-warm while the rest of the fleet stays
down, because `ensure_daemon_running()` still honors the machine-wide
kill-switch (no fleet-recovery revival). Flags: local
`.janitor/state/maintenance-mode` or global `maintenance-mode.flag`;
controlled via `/janitor-maintenance-mode` (local `on`/`off`/`global`) or
`global_control_cli.py maintenance|maintenance-off`. See the LOCAL-scope
notes `reference_maintenance_mode_cache_warm_vs_disarm` (the cost model) and
`feedback_arming_one_session_wakes_the_whole_fleet` (the incident that
motivated it — clearing the global kill-switch to keep one session's
heartbeat alive woke the whole fleet; maintenance-mode avoids that).

### Control flow — daemon

`daemon.py` acquires the singleton flock (else exits). Each tick it runs the due
`Task`s; `_run_workload` runs the subprocess under a **1800s cap** with periodic
heartbeat ticks. `Task.run()` stamps `<name>.last-run.ts` **unconditionally in
`finally`** — so a stale last-run stamp means the task is not *running*, not
that it is failing silently. Every `claude plugin marketplace update` is wrapped
in a cross-process marketplace lock (skip-if-held). The daemon's task set
includes: `marketplace-refresh` (bulk, ~1200s), `version-update` (janitor self-update, ~21600s, sets
the reload flag), plus the opt-in OAuth-rotator beats and the Tier-1 memory
guard (below). For the FULL beat schedule — every daemon `Task` with its exact
cadence, the dynamic per-session heartbeat tiers, and the single-writer /
fleet-exclusion **limitations** that put a whole class of work on the slow clock
— see [[janitor-beat-tasks-and-limitations]].

## The scope invariant (HARD RULE — issue #7, PRRD S2.1)

This is the load-bearing rule the whole two-tier split exists to enforce:

- **user/global-scope ops → the daemon ONLY.** Argless bulk `claude plugin
  marketplace update`, `claude plugin update --scope user`, and janitor
  self-update are daemon-exclusive.
- **project/local-scope ops → per-session detectors.** They hard-filter to
  `scope in (user, managed)`-rejection and only ever pass a specific
  `<marketplace>` argument — never the argless bulk form.
- A cheap idempotent **file** write to user scope (e.g. installing rule files)
  may stay per-session **but MUST be atomic** (tmp file + `os.replace`) — the
  file analogue of the daemon's single-writer lock (PRRD S3.1).

User-scope detectors that look like they mutate (e.g. `version-update`; formerly
`user-plugins-update`, retired 2026-08-20 TRDD-E39YT9G6 — the harness self-updates
user-scope plugins) are actually thin **shims** that delegate to the daemon and
emit a staleness drift line if the daemon's stamp is old — they never perform
the mutation themselves.

## Self-healing must reach every respawn path

The daemon has TWO respawn paths: the session/heartbeat path (the stub →
`ensure_daemon_running` → `spawn_daemon_detached`) and the OS path
(launchd/systemd KeepAlive → `daemon_keepalive_entry` → `daemon.main`). A
self-healing SIGNAL — the C3 quarantine (a proven-bad version) and the
crash-loop breaker — only heals if EVERY respawn path both *consults* it and
*feeds* it. A signal wired to one path silently covers half the failure
surface; the keepalive and the stub must agree on which version is bad and both
must report a crash.[^3]

## Historical detail (atoms, verbatim)

^ATOM-HTZM-49B5 [desc:"CLAUDE.md's original purpose note + the two-tier 'what it is' overview (verbatim historical text, kept for provenance)", keywords: compact_map_recall_janitor_without_re-reading_tree what_it_is_two_tiers per_session_heartbeat_cron_five_minutes global_daemon_owns_user_global_scope_mutation why_is_the_janitor_cron_session-scoped does_the_janitor_cron_survive_a_claude_restart what_is_the_janitor-renew_marker_for how_many_detectors_and_pattern_libs_does_the_janitor_ship what_is_the_SessionStart_re-arm_nudge what_is_the_two-tier_architecture, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

> **Purpose of this file:** a compact map so a session can recall how the
> janitor works WITHOUT re-reading the tree. Keep it current when structure
> changes. Verified-detail for the core wiring; grouped lists + conventions
> for the breadth (38 detectors, ~200 pattern libs).

### What it is

A Claude Code plugin that keeps the dev environment tidy & secure. Two tiers:

1. **Per-session heartbeat** — a `CronCreate` per project fires a fresh
   turn every ~5 min → runs **project-scoped** drift detectors `--one-shot` →
   emits one-line "drift" findings to the model. Silent when nothing drifts.
   The cron is **SESSION-SCOPED by platform design** (CC docs: scheduled tasks live
   in the current conversation, are restored only on `--resume`/`--continue`, and
   expire after 7 days — there is **no** `durable` parameter). It therefore cannot
   survive a Claude restart on its own: the SessionStart re-arm nudge and the
   `[janitor-renew]` marker ARE the survival mechanism, not workarounds for a bug.
2. **Global daemon** — ONE machine-wide singleton process that owns every
   **user/global-scope** mutation (so N sessions don't stampede the same
   command — issue #7). Spawned lazily by any session's heartbeat.

^ATOM-N9XA-YR3U [desc:"The scope invariant bullets verbatim: user/global-scope ops go to the daemon only, project/local-scope ops stay per-session, atomic file writes are the one exception", keywords: scope_invariant_hard_rule_issue_7 user_global_scope_ops_daemon_only project_local_scope_ops_per_session_detectors atomic_file_writes_user_scope_rules why_must_a_bulk_marketplace_update_go_through_the_daemon what_stops_N_sessions_from_stampeding_the_same_command what_is_the_tmp_plus_os_replace_pattern which_ops_are_user-scope_vs_project-scope what_is_issue_7 does_a_cheap_idempotent_file_write_need_the_daemon, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

### Scope invariant (HARD RULE — issue #7)

- **user/global-scope ops → daemon ONLY.** Bulk `claude plugin marketplace
  update` (argless), `claude plugin update --scope user`, janitor self-update.
- **project/local-scope ops → per-session detectors.** They hard-filter
  `scope in (user, managed)` and only ever pass a specific `<market>` arg.
- Cheap idempotent **file** writes to user-scope (rules) stay per-session but
  MUST be **atomic** (tmp + `os.replace`) — the file analogue of the daemon's
  single-writer lock for expensive commands.

## Governed by

- [[janitor-architecture]] — the architecture overview hub this page details.

## Notes and lessons learned

[^3]: [id:ATOM-MG07-0008, status:valid, keywords:"bad_self_update_resurrects_at_os_level quarantine_gate_every_acting_path keepalive_ignored_quarantine", ocd:2026-06-25, lmd:2026-06-25] A bad janitor self-update kept
  self-resurrecting at the OS level even though C4 had a rollback
  (TRDD-KEEPQRTN, fixed v0.24.1). Symptom: a bad-DAEMON version relaunched by
  launchd forever — "auto-rollback didn't work for the daemon." Cause: C4's
  quarantine was consulted ONLY by the dispatcher-stub (the heartbeat path); the
  keepalive's `latest_cache_scripts_dir()` picked the newest version REGARDLESS
  of quarantine, and OS-respawns never called `_record_spawn_attempt`, so
  `crash_loop_active` (which counts `daemon.spawn-history`) never saw the
  OS-driven loop → C4 never fired. Fix: the keepalive now SKIPS quarantined
  versions (mirroring the stub's C3 walk, fail-open) AND the keepalive-launched
  daemon records a spawn attempt (fail-open, keepalive-gated so it never
  double-counts the session path). Lesson: this is the SAME shape as the
  rotator's divergent-input-path bug (see [[oauth-rotation-renew-reauth]]) — a
  signal that gates self-healing must be consulted by EVERY path that can act on
  it; wiring it to one path is hidden half-coverage. It survived the per-group
  reviews because C4 (heartbeat) and the keepalive (OS path) each looked correct
  in isolation; only the whole-immortality-surface review caught the cross-group
  seam.
