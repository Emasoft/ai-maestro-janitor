---
name: janitor-beat-tasks-and-limitations
description: "what is the heartbeat rate / how often does the janitor run each task / daemon beat cadences and intervals / list of periodic daemon tasks / why did my user-scope plugin take up to an hour to update / can the per-session heartbeat update user-scope plugins / the single-writer limitation / why the fleet is excluded from auto-update / how fast does a global disarm reach every session / which beats are opt-in / dynamic heartbeat tiers fast mid slow — the janitor's two-clock schedule and its known limitations"
ocd: 2026-07-12
lmd: 2026-07-13
metadata:
  node_type: memory
  type: project
  tier: component
  globs:
    - "scripts/daemon.py"
    - "scripts/dispatch.py"
    - "scripts/lib/heartbeat_cadence.py"
---

# Janitor beat tasks + limitations

The janitor runs on **two independent clocks**. Knowing which clock owns a job —
and its cadence — explains every "why did X take so long to happen" question, and
the **single-writer limitation** is the reason a whole class of work is on the
slow clock at all. This is the component page under [[janitor-architecture]]; read
that hub first for the two-tier model, then this for the exact schedule + limits.

## The two clocks

- **Clock A — the per-session heartbeat** (project scope): a `CronCreate`, one per
  project, fires a fresh Claude turn. Runs the project-scoped detectors and surfaces
  drift + resume/renew/reload markers. Silent when nothing drifts. **It is
  SESSION-SCOPED, by platform design** — Claude Code scheduled tasks live in the
  current conversation, are restored only on `--resume`/`--continue`, and auto-expire
  after 7 days; there is **no** parameter that outlives the session. The heartbeat
  therefore CANNOT survive a Claude restart on its own, and the SessionStart re-arm
  nudge + the `[janitor-renew]` marker are not workarounds for a bug — they ARE the
  survival mechanism.[^cron-session-scoped]
- **Clock B — the global daemon loop** (`daemon.py`): ONE machine-wide singleton,
  loop ceiling **60 s**. Each tick runs every DUE `Task` (`Task.is_due()` gates on
  its interval; `Task.run()` stamps `<name>.last-run.ts` unconditionally in
  `finally`, so a stale stamp = "not running", never "silently failing").

A job is on Clock B (not A) precisely when it is a **user/global-scope mutation**
that N concurrent sessions must not each run — the single-writer invariant below.

## Clock A — heartbeat cadence (dynamic, TTL-aware; TRDD-0QQX9H0G / #83)

The fire is NOT a fixed `*/5` anymore. `dispatch.py` self-selects a tier each fire
(`heartbeat_cadence.py`), re-arming via the reused `[janitor-renew]` channel when the
armed tier differs from the desired one (dispatch can't call `CronCreate` — a model
tool — so it asks the model to re-arm). Shipped tier crons (SLOW-TTL regime, each
config-overridable via `heartbeat_cron_{fast,mid,slow}`):

| Tier | Cron | When |
|---|---|---|
| FAST | `*/5 * * * *`  | actively waiting — rate-limit flag, post-compact resume, pending resume directive, `keep-going`, or a pending background agent. **Same FIRING FREQUENCY as pre-#83** (no regression there); the worst-case recovery GAP is the period PLUS cron jitter — the two sources disagree (CronCreate tool: ≤10% of the period, max 15 min; CC docs: up to half the interval for sub-hourly — checked 2026-08-02), so `*/5` ≈ 5 min + 0.5–2.5 min.[^2] |
| MID  | `*/15 * * * *` | recent user activity (presence breadcrumb fresh) but nothing waiting. 3× cheaper than `*/5`. |
| SLOW | `*/30 * * * *` | idle keep-warm / maintenance. 6× cheaper than `*/5`; 30-min gaps stay under the 1 h subscription cache-TTL. |

`*/30` is the **safe floor** for a uniform cron: any `*/N` with 30 ≤ N < 60 fires
exactly twice an hour (minutes 0 and N), so `*/45` is no cheaper than `*/30`; only a
single-minute hourly cron beats 2/h and its 60-min gap == the TTL (too tight).
**Hysteresis:** promote to a faster tier immediately; demote only after
`heartbeat_cadence_demote_fires` (default 2) consecutive quiet fires — no flapping.
Under a **fast-TTL regime** (cache-TTL < 30 min, e.g. API-key auth) all tiers collapse
to `*/5` (no safe slowdown). Off entirely when `heartbeat_cadence_dynamic` is false ⇒
the fixed `CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON` (default `*/5`). Why it exists: a quiet
fire on a ~510k-context session ≈ 507k cache_read ≈ $0.76, so `*/5` idle ≈ ~$9/h just to
stay cache-warm; demoting to SLOW cuts that ~6×.

## Clock B — the daemon beat tasks (`_build_tasks`)

Every periodic daemon Task, its DEFAULT interval, and what it does. Each interval is
overridable via its `CLAUDE_PLUGIN_OPTION_DAEMON_*_INTERVAL` env var. [^1]

| Task | Interval | Purpose / opt-in |
|---|---|---|
| `marketplace-refresh` | **1200 s (20 min)** | bulk `claude plugin marketplace update` (all marketplaces) — the daemon is the sole global-refresh writer. |
| `user-plugins-update` | **3600 s (1 h)** | full `--scope user` plugin sweep (~7 min); EXCLUDES the ai-maestro fleet. |
| `version-update` | **21600 s (6 h)** | janitor self-update when GitHub is ahead of the cache; sets the reload flag. |
| `oauth-rotator-supervisor` | **600 s (10 min)** | OAuth-rotator governance/alerts. **No-op unless `/janitor-auto-manage-oauth-on`.** |
| `oauth-rotator-tick` | **60 s** | refresh the LIVE OAuth credential. **No-op unless opted-in AND a real `claude` is running.** The one beat that still runs under MAINTENANCE (a lapsed token would break the fleet). |
| `memory-guard` | **120 s (2 min)** | Tier-1 OOM guard — one cheap free-mem read; the ps-snapshot + kill only runs under real memory pressure. |
| `cache-prune` | **21600 s (6 h)** | prune stale plugin-cache version dirs (machine-global). |
| `rules-cleanup` | **3600 s (1 h)** | remove orphaned installed rules ONLY when the janitor is CONFIRMED fully uninstalled (the daemon outlives the plugin on its orphaned cache ~7 d). |
| `session-liveness` | **120 s (2 min)** | fleet-guardian — recover a frozen/cron-dead/version-mismatched session; per-instance 15-min cooldown. The immortality the in-session cron can't provide. |
| `fleet-stop` | **60 s (1 min)** | reach every armed session with a machine-wide disarm/pause within ~1 min. **No-op unless `CLAUDE_PLUGIN_OPTION_FLEET_STOP_ENABLED=1`.** |

**Not cadenced — per-loop consumers** (run EVERY daemon loop, after the
stop/pause/maintenance branches, before the due-loop): `_consume_version_update_request`
and `_consume_plugin_update_requests` drain the request QUEUEs a per-session detector
raised, so a signalled update lands in ≤ ~60 s rather than waiting for the 6 h / 1 h
beat. This is the request-flag→daemon-consume substrate (see the limitation below).

## The load-bearing limitation — single writer (issue #7 / PRRD S2.1)

**Every user/global-scope command runs on Clock B ONLY.** The per-session detectors
hard-refuse `scope in (user, managed)` and only ever pass a specific `<marketplace>`
arg — they never run argless bulk `claude plugin marketplace update`, `claude plugin
update --scope user`, or the janitor self-update. Reason: N sessions across N projects
would stampede the same machine-global command. The daemon holds a cross-process
marketplace lock (skip-if-held) and is the SOLE writer.

Consequence + the fix: a behind user-scope plugin used to lag up to the daemon's **1 h**
`user-plugins-update` sweep (the janitor's own 0.39→0.41 sat for hours — the symptom that
motivated this). The single writer can't be given up, so the detector **SIGNALS** and the
daemon **WRITES**:
- **[[TRDD-Y9KM5RCJ]]** — the `version-update` detector raises `request_version_update()`;
  the daemon consumes it each loop → janitor self-update in ~5-6 min, not 6 h.
- **TRDD-YMTUPQER** — the `plugin-updates` detector enqueues `request_plugin_update(id,
  "user", …)` for every behind user-scope plugin; the daemon consumes → update in ~5-6 min,
  not 1 h. Single-writer preserved (detector signals, daemon writes).

A cheap idempotent **file** write to user scope (installing rule files) may stay
per-session but MUST be atomic (tmp + `os.replace`) — the file analogue of the lock
(PRRD S3.1).

## The second limitation — the ai-maestro fleet is excluded (TRDD-db169d9e R2)

The ai-maestro fleet plugins (maintainer / orchestrator / CPV / …) are **never
auto-updated one-at-a-time** — not by the daemon's 1 h user sweep and not by the
YMTUPQER signal path. `state.is_ai_maestro_plugin_id()` (the `@ai-maestro-plugins`
suffix is authoritative) excludes them in BOTH the detector (don't signal) and the
daemon consumer (don't act, defense-in-depth). Fleet versions are owned by each
plugin's own release pipeline; auto-bumping them piecemeal causes version skew. The
janitor's OWN id is excluded here too — its self-update is the separate
`version-update` / Y9KM5RCJ path (USER decision 2026-07-12, AskUserQuestion: "all
user plugins EXCEPT the ai-maestro fleet").

## Other cadence caveats

- **Heartbeat modes** (`_resolve_heartbeat_mode`): FULL runs due detectors + daemon
  spawn; MAINTENANCE fires cache-refresh-only (no detectors, no daemon spawn) at the
  0.1× cache-read rate; STOP self-disarms (`[janitor-self-disarm]` → `/janitor-disarm`
  deletes the cron). The cadence phase runs in both FULL and MAINTENANCE (maintenance ⇒
  idle ⇒ SLOW).
- **Opt-in beats cost nothing when off:** the OAuth-rotator, fleet-stop, and (via the
  opt-in flag) other gated tasks are no-ops for a non-opted-in install, so their fine
  cadences are free.
- **Fail-soft (PRRD S6.1):** a detector/task that raises or whose optional dependency
  is missing degrades to zero findings and logs once — one broken unit never crashes the
  heartbeat or blocks the others.

## Governed by

- [[janitor-architecture]] — the two-tier hub this page details the schedule for.

## See also

- [[oauth-rotation-renew-reauth]] — what the 60 s `oauth-rotator-tick` / 10 min
  supervisor beats actually do.
- [[agentlens-diagnostics-integration]] — the observability detectors' optional
  agentlensPro cross-check (informs the TTL-regime probe direction).


^ATOM-PHXC-VE71 [desc:"The full CLAUDE.md 'Control flow' section verbatim: dispatch.py's numbered heartbeat steps 1-8+3a, the daemon loop + background bulk lane, and the release-triggered self-update fast path", keywords: control_flow_heartbeat_dispatch.py_steps_numbered daemon_loop_bulk_lane_background_tasks release_triggered_self_update_version-update-requested_flag dispatcher_stub_os.execv_auto_roll, type: project, ocd: 2026-08-02, lmd: 2026-08-02] [^2]

### Control flow

**Heartbeat (per session):** cron prompt → `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py`
(re-resolves latest cached `<ver>/scripts/dispatch.py`, `os.execv`s into it — so
plugin updates auto-roll with NO re-arm) → `dispatch.py`:
1. `rate-limited.flag` present → emit `[janitor-resume]`, clear flag (also clears the compact-resume flag).
2. `resume-after-compact.flag` present → emit `[janitor-resume] …continue TRDD-xxxx…`, clear flag (post-compact auto-resume; the PostCompact hook wrote it — TRDD-31095269).
   Both resume phases also stamp `last-resume.ts` and RETURN EARLY. The stamp is the cadence phase's ONLY view of a resume — it runs later in the same `main()`, by which point the flag is already unlinked, so reading the flags there is dead code (fixed 2026-07-11).
3. cron near 7-day expiry → emit `[janitor-renew]` (Claude re-runs /janitor-arm).
3a. **dynamic TTL-aware cadence** (TRDD-0QQX9H0G, #83): pick a tier from live state — FAST `*/5` (actively waiting: a `last-resume.ts` stamp <30min old / pending directive / pending agents / keep-going — same firing FREQUENCY as pre-#83; worst-case gap = period + cron jitter, sources disagree on the jitter), MID `*/15` (recent user activity), SLOW `*/30` (idle) — bounded by the REAL cache-TTL (authoritative via the `agentlenspro get_account_status` probe → `cacheTtl.minutes`, fail-open + cached; fast-TTL regime <30min ⇒ all tiers `*/5`). Writes `desired-cadence.cron`; RE-USES `[janitor-renew]` to re-arm when the armed tier differs (dispatch can't call CronCreate). Runs after the resume/keep-going phases; the SLOW tier is the only sanctioned answer to cost (fewer fires, same work) since the self-budget clamp was removed; hysteresis (`heartbeat_cadence_demote_fires`, default 2) demotes slowly, promotes now. No-op when `heartbeat_cadence_dynamic` is off. Cuts idle heartbeat cost ~6x (measured: a quiet fire on a ~510k-context session ≈ 507k cache_read ≈ $0.76; `*/5`=12 fires/h → ~$9/h idle vs `*/30`=2/h). `*/30` is the safe floor — any `*/N` with 30≤N<60 fires exactly 2×/h, so a slower uniform cron needs a 60-min (at-TTL) gap.
4. `ensure_daemon_running()` (lazy-spawn the singleton if dead).
5. daemon stale/old-version → request restart (auto-roll the daemon too).
6. run each **due** detector `--one-shot`; emit only NEW findings (seen-file dedupe).
7. `reload-needed.flag` → emit `[janitor-reload]` (Claude runs /reload-plugins).
8. `skills-reload-needed.flag` (bumped by `/janitor-global-reload-skills`) → emit `[janitor-reload-skills]` once-per-session (per-project ack) → Claude runs /janitor-reload-skills → /reload-skills (standalone non-plugin skills/commands). TRDD-LQU7OXXV.

**Daemon loop (`daemon.py`):** acquire singleton flock (else exit) → every tick,
run each due `Task`; `_run_workload` runs subprocess with **1800s cap** +
periodic heartbeat ticks. `Task.run()` stamps `<name>.last-run.ts`
**unconditionally** in `finally` (so stale last-run = task not *running*, not
failing-silently). **Background bulk lane (TRDD-H7NVKSAX, 2026-07-17 oauth-starvation
incident):** the BULK tasks (`marketplace-refresh`, `user-plugins-update`,
`version-update`, `github-config-audit`) carry `background=True` and run in ONE detached
child at a time (`daemon.py --run-task <name>`, parent reaps + stamps from the child rc)
so a ~20-min bulk run can NEVER block the loop's 60s survival beats (oauth-rotator-tick
above all — two back-to-back 1190s marketplace refreshes once blinded rotation while an
account hit its 5h wall). One lane preserves the old bulk-chore serialization; file locks
remain the backstop. Tasks: `marketplace-refresh` (3600s — was 1200s, which ≈ its own
runtime and gave a 50% duty cycle; bulk), `user-plugins-update`
(3600s, `--scope user`), `version-update` (21600s, self-update + sets reload-flag),
`rules-cleanup` (3600s, TRDD-H9IBY95W — when the janitor is CONFIRMED uninstalled, removes
provenance-marked orphaned rules from `~/.claude/rules/`; the only actor that can act after a
full uninstall since CC has no uninstall hook + the daemon outlives the plugin on its orphaned
cache ~7d; opt-out `CLAUDE_PLUGIN_OPTION_RULES_CLEANUP_ENABLED`; NEVER touches memory).
All marketplace updates wrap `gs.marketplace_lock()` (skip-if-held).
**Release-triggered self-update (TRDD-Y9KM5RCJ):** the 6h `version-update` beat is too
slow to land a fresh janitor release (v0.41.0 sat at cache 0.39.0 for hours). The
per-session `version-update` detector now RAISES `gs.request_version_update()`
(`version-update-requested.flag`, global-state) when the cache is behind GitHub AND
`auto_update_on_new_release` is on; the daemon's `_consume_version_update_request(tasks)`
runs each loop AFTER the stop branch, BEFORE the due-loop —
clear-before-run, then `version-update` Task `.run()` NOW (≤~60s). Single-writer preserved
(the detector only requests; issue #7/PRRD S2.1). Latency ~5-6min not 6h. Opt-out
`CLAUDE_PLUGIN_OPTION_VERSION_UPDATE_ON_RELEASE_TRIGGER`; fail-open to the 6h beat.

## Notes and lessons learned

[^1]: [id:ATOM-MG06-0014, status:valid, keywords:"verify_cadence_against_source_constants staged_plan_is_not_what_runs interval_default_cron_source_of_truth", ocd:2026-07-12, lmd:2026-07-12] Verified the beat cadences against
  `scripts/daemon.py` `_INTERVAL_*` constants and the tier crons against
  `heartbeat_cadence.py` `_DEFAULT_CRON` at authoring time (0.41.0-dev). The plan file
  `staged-kindling-lynx.md` proposes a DIFFERENT `*/15`/`*/30`/`*/45` tier set plus an
  agentlensPro TTL probe — that is UNIMPLEMENTED; the shipped tiers are `*/5`/`*/15`/`*/30`.
  Lesson: verify cadence numbers against the `_INTERVAL_*`/`_DEFAULT_CRON` source, not a
  staged plan — a plan describes what MIGHT ship, not what runs.

[^cron-session-scoped]: [id:ATOM-MG06-0015, status:valid, keywords:"durable_cron_parameter_does_not_exist session_scoped_cron_by_design inferred_platform_guarantee_from_param_name", ocd:2026-07-13, lmd:2026-07-13] This page previously called Clock A
  "a **durable** `CronCreate`", and the codebase (CLAUDE.md, the `/janitor-arm` skill,
  ai-maestro-janitor#23) treated every session-only cron as a BUILD BUG — "some Claude Code
  builds silently downgrade `durable: true` to session-only". That framing is WRONG. A
  2026-07-13 sweep of the official docs (`tools-reference`, `scheduled-tasks`) found **no
  `durable` parameter at all**: scheduled tasks are documented as *session-scoped* — they
  live in the current conversation, are restored only on `--resume`/`--continue`, and expire
  after 7 days; the docs point to Routines / desktop scheduled tasks / GitHub Actions for
  anything that must outlive a session. So the cron never "downgraded"; it always behaved as
  designed and `durable: true` was simply an ignored argument. WHY the error persisted: we
  inferred a platform guarantee from a parameter NAME we passed, and when observation
  (session-only) contradicted the inference we filed a bug against the platform instead of
  checking the spec — the same "a name is a hypothesis, not a contract" trap. Consequence
  worth keeping: the SessionStart re-arm + `[janitor-renew]` are not a workaround for an
  upstream defect, they are the ONLY survival mechanism, so they must never be "cleaned up"
  once #23 is closed. Lesson: before filing a platform bug, READ THE SPEC — an argument the
  platform ignores is not a broken promise, it is a promise never made.
[^2]: [id:ATOM-0AOD-B2GJ, status:valid, desc:"The tier table's latency claim ignored cron jitter; the two jitter sources disagree", keywords:"recovery_latency_cron_jitter heartbeat_tier_worst_case_gap cron_fires_late_sources_disagree measure_fire_times_not_turn_end janitor_resume_slow_after_compact", ocd:2026-08-02, lmd:2026-08-02] DO NOT quote a heartbeat tier's recovery latency as exactly its cron period (this page pre-2026-08-02 read 'FAST */5 — recovery latency unchanged / ZERO regression'), BECAUSE a scheduled fire lands LATE by a documented jitter and the two sources for it DISAGREE (CronCreate tool: <=10% of the period, max 15 min; CC docs page: up to HALF the interval for sub-hourly tasks — both checked 2026-08-02), so */5 is really ~5 min + 0.5-2.5 min and */30 is ~30 min + 3-15 min. DO state period + jitter range with source and check date, and measure the real distribution ONLY from FIRE timestamps (.janitor/logs/heartbeat-fires.log, stamped by dispatch.main since TRDD-LI7ENU2A) — never token-meter turn-END times, whose ts-mod-300 is UNIFORM (they measure turn duration, not jitter).
