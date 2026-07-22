---
name: janitor-architecture
description: "how does the ai-maestro-janitor work / what runs the drift detectors / where does janitor state live / why a daemon AND a heartbeat / how does it survive a freeze or crash / what makes it immortal (the L0-L3 keepalive + watchdog layers) / what is the scope invariant / which detector finds X / where are the pattern libs — the architecture overview hub"
ocd: 2026-06-13
lmd: 2026-07-22
metadata:
  node_type: memory
  type: project
  tier: hub
  globs:
    - "scripts/**"
    - "skills/**"
    - "CLAUDE.md"
    - "design/requirements/PRRD.md"
---

# ai-maestro-janitor — architecture hub

The janitor is a Claude Code plugin **with no main agent** that keeps the dev
environment tidy and secure. It runs as two cooperating tiers: a **per-session
heartbeat** that surfaces project-scoped drift to the model, and **one
machine-wide daemon** that owns every user/global-scope mutation. This page is
the navigable prose layer over the auto-generated project map in `CLAUDE.md` —
read this to understand *how the pieces fit*, then drop into `CLAUDE.md`'s
fenced map for the exact file/symbol index.

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
includes: `marketplace-refresh` (bulk, ~1200s), `user-plugins-update`
(`--scope user`, ~3600s), `version-update` (janitor self-update, ~21600s, sets
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

User-scope detectors that look like they mutate (e.g. `user-plugins-update`,
`version-update`) are actually thin **shims** that delegate to the daemon and
emit a staleness drift line if the daemon's stamp is old — they never perform
the mutation themselves.

## Detector roster (project-scoped — never touch user scope)

Each detector is a standalone `--one-shot` script driven by `dispatch.py`, with
its own cadence and seen-file dedupe. Slow ones use a PID-tracked detached
worker that skips if the prior worker is still alive. By function:

- **git / workflow hygiene** — pr-reconciler, worktree-janitor, dirty-tree,
  tracked-ignored, nested-git-safety, branch-protection, stale-stash,
  task-pr-mismatch, stale-task.
- **TRDD / task** — trdd-drift, trdd-reminder, report-to-trdd-drift,
  project-map-drift.
- **cleanup** — screenshot-purge, trashcan-purge.
- **scope drift** — settings-scope-drift, claude-md-scope-drift,
  cross-scope-reference-drift, subagent-scope-drift, mcp-config-drift.
- **supply-chain / security** — mcp-rugpull, remote-credentials,
  supply-chain-fingerprints, typosquat-watcher, provenance-audit,
  repo-trust-score, package-manager-policy, workflow-security,
  historical-cache-scan, binary-magic-scanner, ai-context-poisoning,
  subagent-report, janitor-self-integrity.
- **memory** — memory-librarian (SURFACES aggregation/conflict candidates,
  never mutates), memory-scope-leak (keeps the PUSHED memory scope free of
  machine/user-private data).
- **observability** — token-usage-anomaly (token-cost drift vs a learned baseline),
  window-burn-rate (early-rate-limit alarm); both ENRICH/CROSS-CHECK with the optional
  agentlensPro CLI — see [[agentlens-diagnostics-integration]].
- **updates (daemon-delegating shims)** — marketplace-refresh, plugin-updates,
  local-plugins-update, project-plugins-update, user-plugins-update (shim),
  version-update (shim).
- **OAuth (opt-in)** — oauth-cookie-reminder, oauth-login-needed.

**Fail-soft contract (PRRD S6.1):** every detector that raises, or whose
optional dependency is missing, degrades to zero findings and logs once. A
single broken detector MUST NOT crash the heartbeat or block the others.

## The pattern libraries (`scripts/lib/*_patterns.py`, ~200+)

The security knowledge base lives as one module per attack class
(`<domain>_patterns.py` — e.g. `cloud_credential_patterns`,
`prompt_injection_patterns`, `npm_lifecycle_patterns`, `k8s_admission_patterns`).
Uniform shape: each exposes regex/rule definitions plus metadata consumed by the
scanner detectors. There are too many to enumerate — grep by domain when you
need one. The shared primitives the scanners build on are in
`security_helpers.py` (entropy, base64-sniff, Levenshtein/typosquat, invisible-
Unicode, authority-impersonation, advisory-armor) and `ioc_taxonomy.py`.

## Skills (`skills/`)

Contributor-facing, user-invocable entry points: `janitor-arm` /
`janitor-disarm` (install the stub + arm/tear-down the cron),
`janitor-supply-chain-watcher`, `janitor-dependabot-doctor`,
`janitor-credential-window-audit`, `janitor-github-workflow-doctor`,
`janitor-github-workflow-create`, `janitor-fork-pr-cache-audit`,
`janitor-compact-context` (agent-invocable self-compact + auto-resume),
and the memory trio `janitor-memory-write` / `janitor-memory-update` /
`janitor-memory-recall`. The OAuth and repomap toggles
(`/janitor-auto-manage-oauth-on|off`, `/janitor-auto-repomap-on|off`) and the
autofix toggles (`/janitor-autofix-on|off`) gate the opt-in subsystems.

## Resilience pillars (TRDD-7100178d)

The daemon is engineered to survive corruption and resource exhaustion:

- **Pillar 2 — file integrity** (`janitor_integrity.py`): critical writes use a
  redundant mirror (`backup_and_write`) and corruption-recovering reads
  (`read_or_restore`); the rotator's `state.json` and slot index are persisted
  through this path so a torn write self-heals instead of bricking the daemon.
- **Pillar 4 / Phase 5 — Tier-1 OOM memory guard** (`memory_guard.py`,
  user-signed): a daemon task samples system free memory and the process table,
  and when memory is critically low kills the single largest-RSS *Tier-1-
  killable* process (never a protected PID, never a too-young process) — SIGTERM
  → grace → SIGKILL. This is what keeps an unattended host from locking up under
  memory pressure.
- **Self-integrity** (`janitor_self_integrity.py` + the
  `janitor-self-integrity` detector): HMAC-signed drift lines, an append-only
  HMAC-chained audit log, and a manifest of the plugin's own files so tampering
  with the janitor surfaces as a finding.

## Immortality — layered self-resurrection (TRDD-324223a6)

The pillars above keep the daemon from corrupting itself; this layer keeps the
whole system *recovering from a frozen or dead session by any means*. The freeze
it fixes was structural — the recovery trigger used to live INSIDE the session it
had to rescue (a session-only heartbeat), so once that session wedged, nothing
outside could re-fire it. Four layers, each resurrecting the one below:

- **L0 — OS keepalive** (GROUP B, shipped v0.18.0): a launchd agent (macOS) /
  systemd unit (Linux) with `KeepAlive` + `RunAtLoad`, installed at a FIXED
  `${CLAUDE_PLUGIN_DATA}` entry, respawns the daemon on crash, logout, or boot —
  even with zero Claude sessions alive. All persistence tokens live in a shell
  installer (a resolving heredoc the CPV persistence-target discriminator can
  downgrade to inert); the Python orchestrator stays token-free, so REAL
  persistence ships past `--strict` without suppressing a finding (PRRD S5.1).
- **L1 — daemon watchdog** (GROUP A): the singleton daemon detects a frozen
  session (stale transcript + rate-limit flag) and drives a 7-rung recovery
  ladder — gentle first (ESC-nudge → `/janitor-arm` → `/reload-plugins` →
  update), then nuclear (relaunch → external-kill+relaunch → background-`claude`
  resurrect). Injection is terminal-env-aware (iTerm-UUID osascript / tmux
  send-keys / ai-maestro CLI), NEVER kills the user's interactive session (honors
  the OOM guard's protected PIDs), and is crash-loop-guarded (after N nuclear
  attempts it pauses and alerts a human — the one place recovery yields).
- **L2 — session hooks**: SessionStart re-arms the cron, publishes the session
  registry, and captures the terminal identity; PostCompact records a resume
  directive so a compaction can't strand an unattended session.
- **L3 — in-session cron**: the ~5-min heartbeat self-trigger. Session-only is
  acceptable here precisely because L2 re-arms it every new session.

The self-integrity pillar above became FUNCTIONAL in this initiative's GROUP C
C1 (shipped v0.18.0): `publish.py` regenerates `.integrity/manifest-sha256.json`
on every release, giving the `janitor-self-integrity` detector a fresh
per-release baseline. The exec-path hardening (verify-before-exec gate,
pin-last-good, auto-rollback) is deliberately DEFERRED to reviewed design — a bug
in the heartbeat's own exec path bricks the very lifeline it guards.

## Filesystem & state conventions

| Path | Resolves to | Lifecycle | Use for |
|---|---|---|---|
| `${CLAUDE_PLUGIN_ROOT}` | the versioned plugin cache dir | **ephemeral** — changes every update, GC'd ~7 days | scripts, skills, hooks. **NEVER write state here.** |
| `${CLAUDE_PLUGIN_DATA}` | the per-plugin persistent data dir | **persistent** — survives updates, backed up, purged only on uninstall | ALL persistent state, caches, venvs. **Prefer this** (PRRD S4.1). |
| `<repo-root>/.janitor/state/` | per-project | per-project | per-session detector state (last-run stamps, seen-files, resume/rate-limit flags) |

The **auto-rolling dispatcher stub** lives in `${CLAUDE_PLUGIN_DATA}` (correct —
survives version bumps). The daemon's **private** global state is CANONICALLY at
`${CLAUDE_PLUGIN_DATA}/global-state/` since TRDD-2U8AH82F.[^4] Its
**coordination** state — anything a SECOND chore owner must observe or contend
on — instead lives at the fixed `~/.claude/janitor-control/`: see
[[janitor-fleet-control-plane]] for the split, which is audience-based, not a
reversal of the DATA-dir principle.[^11]
Existing installs are migrated automatically by the daemon under its singleton
flock (flock-moves-LAST: the NEW dir's flock is acquired before the
`migrated-from-legacy.ts` marker flips resolution); control-flag readers
dual-read the legacy `$HOME/.claude/janitor-global-state/` for version skew,
and that legacy dir survives only as a tombstoned read-fallback until an EHT
retires it (~2 releases out).

**Principle (per the project owner):** prefer `${CLAUDE_PLUGIN_DATA}` over any
new `$HOME/.claude/<custom>/` folder — the data dir is the only location
guaranteed preserved across plugin/marketplace/version changes, picked up by
backups, and cleanly purged on uninstall.

## Project rules (PRRD pointers)

The constitution is `design/requirements/PRRD.md`. The rules that most shape the
architecture: **G1.1** (GitHub posts self-identify the authoring Claude — all
AI Maestro agents share the one owner gh identity); **S2.1** (the scope
invariant above); **S3.1** (atomic user-scope file writes); **S4.1** (state in
`${CLAUDE_PLUGIN_DATA}`); **S5.1** (publish validates via the CPV plugin only —
clear a finding by devitalizing/removing code, never by suppressing a rule or
relaxing `--strict`); **S6.1** (every detector is fail-soft).

## Self-healing must reach every respawn path

The daemon has TWO respawn paths: the session/heartbeat path (the stub →
`ensure_daemon_running` → `spawn_daemon_detached`) and the OS path
(launchd/systemd KeepAlive → `daemon_keepalive_entry` → `daemon.main`). A
self-healing SIGNAL — the C3 quarantine (a proven-bad version) and the
crash-loop breaker — only heals if EVERY respawn path both *consults* it and
*feeds* it. A signal wired to one path silently covers half the failure
surface; the keepalive and the stub must agree on which version is bad and both
must report a crash.[^3]

## See also

- `CLAUDE.md` — the auto-generated, always-current project map (file → symbol
  index) this hub narrates. When the structure changes, the map is the source
  of truth; reconcile this prose to it.
- `design/requirements/PRRD.md` — the project's golden/silver rules.
- LOCAL scope — anything machine-specific (the host's actual global-state path,
  the OAuth rotator's account/keychain particulars, absolute home paths) lives
  in LOCAL-scope notes, NOT here. This page is git-tracked and host-global, so
  it stays generic by design.
- LOCAL-scope notes `reference_maintenance_mode_cache_warm_vs_disarm` and
  `feedback_arming_one_session_wakes_the_whole_fleet` — the maintenance-mode
  cost model and the fleet-wake incident that motivated it.
- [[janitor-keepalive-test-isolation-fsevents]] — the L0 keepalive's call-time
  state resolution, the test-isolation levers (`JANITOR_GLOBAL_STATE_DIR` /
  `JANITOR_DATA_DIR`, not `CLAUDE_PLUGIN_DATA`), and the bounded restage — the
  fseventsd-runaway class (TRDD-ZNN0UK5K).
- [[janitor-fleet-guardian-reachability]] — why the status table's `armed` column
  is not "the heartbeat is running", why `/janitor-global-arm` arms nothing, and
  why the launchd daemon logged `UNREACHABLE ({})` for 254 beats (stripped PATH
  for tmux; no TCC Automation grant for iTerm). The counterpart to the
  Immortality section above: the OS-keepalive bought the guardian durability and
  cost it its injection channels.

- [[janitor-fleet-control-plane]] — the fixed `~/.claude/janitor-control/`
  directory: what moves there and why the scope rule is AUDIENCE, plus the
  dual-LOCK (not dual-READ) migration a coordination lock requires.

- [[three-pillars-rules-ownership]] — which repo owns each TRDD/PRRD/kanban
  rule file, the pinned `aimaestro-*` overlay names, and the user-scope
  orphans that make an agent read two generations of one rule.

## Notes and lessons learned

[^1]: [id:ATOM-MG07-0006, status:valid, keywords:"hub_is_prose_overlay_not_second_copy auto_map_wins_structural_disagreement fix_prose_not_map", ocd:2026-06-13, lmd:2026-06-13] This hub is the prose overlay of the
  fenced `CLAUDE.md` repomap, not a second copy of it. The map enumerates files
  and symbols and is regenerated automatically; this page explains the *why* and
  the *flow* a contributor needs before reading the map. If the two ever
  disagree on a structural fact, the auto-generated map wins and this prose is
  the thing to fix.

[^2]: [id:ATOM-MG07-0007, status:valid, keywords:"project_user_page_no_machine_private_data no_home_path_email_token_hostname memory_scope_leak_invariant", ocd:2026-06-13, lmd:2026-06-13] PRIVACY: a PROJECT/USER wikimem page is
  git-tracked and host-global, so it MUST NOT carry machine-private data — no
  `$HOME`-expanded absolute paths, no account emails, no OAuth tokens, no
  hostnames. The daemon's real global-state directory, the rotator's account
  details, and any absolute home path are therefore only *named* here as "lives
  in LOCAL scope" and documented generically with `$HOME` / `<repo-root>` /
  `<email>`. The janitor's own `memory-scope-leak` detector polices exactly this
  invariant on the PUSHED memory scope.

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
[^4]: [id:ATOM-MG07-0009, status:valid, keywords:"daemon_state_data_dir_canonical flock_path_is_singleton_guarantee staged_handover_no_two_daemons", ocd:2026-07-07, lmd:2026-07-07] This section previously said the daemon
  state lived in an UNOFFICIAL `$HOME/.claude/janitor-global-state/` folder with
  a standing migrate-to-DATA TODO. Superseded 2026-07-07 by TRDD-2U8AH82F
  (commit ba58ebb): the DATA dir is now canonical via a staged handover. The WHY
  of the staging: the flock path IS the singleton guarantee, so a naive path
  flip would let a new-code daemon lock the NEW dir while an old daemon still
  held the LEGACY lock — two live daemons. Hence resolver-marker + copy under
  the legacy flock + NEW flock acquired BEFORE the marker (both held for the
  daemon's lifetime) + dual-read of control flags for old-code sessions.

[^5]: [id:ATOM-KEEPGO-IDLE, status:valid, keywords:"fleet_idle_overnight agents_did_not_continue heartbeat_did_not_nudge keep_going_off never_stop", ocd:2026-07-16, lmd:2026-07-16, trdd:93TKV769, commits:7cd8ea0]
  DO NOT leave the never-stop keep-going nudge OPT-IN (the pre-2026-07-16 default: silent in full
  mode unless the per-session `keep-going` flag was set), BECAUSE the whole fleet sat idle overnight —
  a healthy heartbeat detected drift and even re-armed `cron_dead` sessions (guardian `rearm` rungs in
  the recovery-audit), but `rearm` restarts the HEARTBEAT, it never tells the agent to keep WORKING,
  so every unattended session that finished a turn with no rate-limit/compact/drift signal went
  silent. DO keep `_phase_keep_going_nudge` DEFAULT-ON in every mode (`keep_going_default=true`),
  silenced only by the explicit `keep-going-off` sentinel (full mode) or the knob — keeping the fleet
  working in the user's absence is the janitor's #1 job, not an opt-in.

[^6]: [id:ATOM-PRESENCE-PERPANE, status:valid, keywords:"USER_PRESENT_wrong_while_absent self_trigger_refused_reload_compact presence_machine_global 30_minute_window per_pane", ocd:2026-07-16, lmd:2026-07-16, trdd:T7N67AQP, commits:"001bb3e,e5888b2"]
  DO NOT gate the self-trigger (`/compact`, `/reload-plugins`) on a MACHINE-GLOBAL presence breadcrumb
  with a 30-min window, BECAUSE a human typing in ANY session then marked EVERY unattended pane on the
  machine "present" for half an hour and the self-trigger refused everywhere (the user kept seeing
  `USER_PRESENT` while absent and had to reload by hand). The gate exists to avoid clobbering a human's
  IN-PROGRESS keystrokes — a harm that lasts seconds and is scoped to the pane they type in. DO make
  presence PER-PANE (`state.terminal_pane_key`: tmux/iTerm/kitty/WezTerm, namespaced by source; ABSENT
  per-pane file = away) with a 5-MIN window; no pane id (Apple Terminal/xterm) falls back to global.
  Inside ai-maestro the signal must come from the SERVER (`aimaestro-session.sh state`/user-idle, or
  `queue`/`--require-idle`), NOT the local breadcrumb — tracked on ai-maestro#73, wired under
  [[trdd-pzlvt2rn]] `#J`.

[^11]: [id:ATOM-MG22-0003, status:valid, keywords:"marketplace_lock_path_moved last_run_stamps_not_in_data_dir control_state_vs_private_state DATA_dir_principle_exception", ocd:2026-07-22, lmd:2026-07-22, trdd:QK7M2B0X, commits:"78879d4"]
  DO NOT read this page's older claim that the marketplace lock and the per-task
  last-run stamps live in `${CLAUDE_PLUGIN_DATA}/global-state/` as current — the
  locks moved to `~/.claude/janitor-control/` in `78879d4` and the stamps are
  scheduled next, BECAUSE a lock only excludes processes contending on the SAME
  inode, so once a second chore owner (an ai-maestro server) exists, a lock it
  cannot find excludes nobody and the collision backstop silently does nothing.
  DO route by AUDIENCE — private state stays in DATA, anything a second owner
  must observe or contend on goes to the fixed control dir
  ([[janitor-fleet-control-plane]]).
