---
trdd-id: X07E7HTN
title: Daemon owns wake-detection so a quiet heartbeat costs zero model turns
column: proposal
created: 2026-07-23T13:46:19+0200
updated: 2026-07-23T13:46:19+0200
current-owner: claude-ai-maestro-janitor
task-type: refactor
approval-tier: 2
relevant-rules: [1]
task-type-detail: architectural change to the heartbeat cost model; standalone-only; survival-critical paths in scope
impacts: [heartbeat-cost-model, survival-resume, fleet-daemon]
release-via: publish
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-23

- **What this is:** a PROPOSAL (Tier 2, MANAGER approval) to make the machine-wide
  OS-keepalive daemon own wake-detection so a QUIET heartbeat costs ZERO model turns.
  Not yet approved; no code written.
- **Core defect:** EVERY `CronCreate` fire is a full model TURN. The stub execs
  `dispatch.py`, which runs ALL due detectors and re-reads the whole transcript at the
  0.1x cache-read rate — ~$0.76 on a 510k-context session — whether or not anything
  drifted. The TTL cadence tiers (`heartbeat_cadence`) only change HOW OFTEN you pay
  that turn; a quiet fire can never be free while the cron IS the trigger.
- **Target mechanism:** the already-existing detached daemon (`daemon.py`, launched by
  launchd/systemd with NO model attached) runs the SAME project detectors detached over
  the fleet it already enumerates (`fleet_scan.gather_fleet`). A QUIET result injects
  NOTHING → zero model turns. A REAL drift finding OR a survival marker
  (rate-limit/compact/clear resume, renew) injects a wake into THAT session's own pane
  via `fleet_inject.fire` — a model turn happens ONLY THEN.
- **NEXT ACTION:** obtain MANAGER approval (Tier 2 — this reshapes the heartbeat cost
  model and touches survival-critical paths). On approval → `git mv` to `design/tasks/`,
  set `column: planned`, then implement per "The fix" below, primary file `scripts/daemon.py`.
- **Load-bearing facts / gotchas (do NOT lose):**
  - The per-session cron MUST stay armed as a fail-open FALLBACK. Removing it silently
    kills overnight survival wherever the daemon path is unavailable (no OS keepalive,
    un-injectable terminal, #J harness).
  - `fleet_inject` can only wake a session with a RESOLVABLE terminal (tmux/iTerm/wtype/
    xdotool/aimaestro CLI). Plain terminals, VS Code integrated terminals, ssh sessions
    have none → the daemon CANNOT wake them → the cron must remain for those.
  - "A cron fire proves the API is reachable" is an invariant the current rate-limit
    resume relies on. A daemon-injected wake does NOT prove reachability — the daemon
    must probe reachability before injecting a `[janitor-resume]`.
  - Daemon-owned wake is STANDALONE-ONLY. In #J harness (`server_is_alive()` /
    `server_runs_chores()`) the daemon does not spawn and continuity is the server's
    (`aimaestro-continuity.sh`). The wake loop gates on `backend(env)=="standalone"` and
    NEVER injects into a `server_owned` instance (TRDD-X92VBFNF hands-off invariant).
  - The daemon sees the WHOLE fleet; the injected wake must carry ONLY the culprit
    project's own findings into the culprit project's pane (TRDD-X92VBFNF per-project
    channeling) AND re-implement `_defang_foreign_markers` (it bypasses dispatch).
  - Any new module the wake loop imports MUST be added to
    `keepalive_stage.daemon_closure` or the OS-spawned daemon crash-loops on a torn
    stage exactly when no session is up.
- **SUPERSEDED — do NOT carry forward:** nothing yet (first revision).
- **Durable artifacts to read before acting:** the Phase-1 implementation map in the
  parent critique (below, "The fix"); `design/ARCHITECTURE.md` §3/§7; the CLAUDE.md
  "Control flow" + "Two runtime backends" sections.

## The problem

The janitor heartbeat's cost is the **model turn itself**, not the detector work inside
it. Control flow today:

```
CronCreate fires every N min (N from the heartbeat_cadence tier)
  → cron prompt runs ${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py
  → os.execv into the latest cached dispatch.py
  → dispatch.main() runs the mode/phase pipeline, then the full _DETECTORS Phase-2 loop
```

Every fire is a full Claude turn that re-reads the ENTIRE append-only transcript at the
0.1x cache-read rate. Measured: one quiet fire on a ~510k-context session ≈ 507k
cache_read ≈ **$0.76**. `*/5` = 12 fires/h → ~$9/h idle; `*/30` (the safe floor,
2 fires/h) → ~$1.5/h idle. The TTL cadence tiers (TRDD-0QQX9H0G) exist ONLY to reduce
how OFTEN a quiet fire is paid — they **cannot make a quiet fire free**, because the fire
IS the turn. `stdout` (a drift line or a marker) only decides whether the model ALSO acts
on top of the turn it already paid for.

In parallel, the daemon ALREADY runs `task_session_liveness` every 120s with NO model
attached: it scans the whole host (`fleet_scan.gather_fleet`), diagnoses each project
(`cron_dead` / `frozen` / `dead` / `rate-limited`), and RECOVERS by injecting ESC +
`/janitor-arm` / `/reload-plugins` into each session's own terminal via
`fleet_inject.fire`. This proves the daemon can already cause a session-local action with
zero model cost. The defect is that wake-detection has not been moved to it: quiet
detector runs still ride a paid model turn instead of a free detached daemon beat.

## The fix (this TRDD's scope)

Move the per-project detector run + the survival-flag watch INTO a new detached daemon
task, and demote the per-session cron to (a) the daemon's resurrection path and (b) a
fail-open fallback. Concrete files + functions (grounded in the Phase-1 map):

### 1. `scripts/daemon.py` — PRIMARY
Add a new detached daemon Task (`wake-detection`, modeled on `task_session_liveness`):
for each fleet `Instance`, run that project's DUE detectors detached and, only when a
finding or a survival marker exists, inject a wake into that session's pane.
- **`Task` / `Task.run` / `Task.spawn_background` / `Task.poll_background`** — register
  the task in the background bulk lane (detached child via `--run-task`; `background=True`)
  so its per-project detector fan-out can NEVER block the loop's 60s survival beats
  (the 2026-07-17 oauth-starvation lesson).
- **`_build_tasks`** — register `wake-detection` with a cadence knob (default 120s,
  mirroring session-liveness).
- **`_run_due_tasks` / `_sleep_seconds`** — schedule it among the due tasks.
- **`main()` loop guards** — place the wake loop STRICTLY AFTER the top-of-loop guards
  (kill-switch, `server_is_alive`, maintenance, global-pause) so a disarmed / server-owned
  / maintenance host is never injected into.
- **`_MAINTENANCE_KEEPALIVE_TASK_NAMES`** — add `wake-detection` (or a survival-only
  sub-mode of it) so a survival wake outlives maintenance exactly like
  `oauth-rotator-tick` does.
- **`_SERVER_ABSORBED_TASK_NAMES` / `_task_yielded_to_server`** — ensure the task yields
  in the harness/server split (the daemon must not spawn wake logic when the server owns
  the host).
- **`_run_task_child`** — the `--run-task wake-detection` worker that performs the
  detached per-project detector execution.

### 2. `scripts/lib/fleet_scan.py` — enumeration substrate (reused as-is)
`gather_fleet` already returns every live claude `Instance` + its `project_root` +
resolved terminal-injection identity + `diagnosis`, reads each project's `.janitor` state,
and sweeps stale rate-limit flags. The wake loop iterates these Instances. `diagnose_root`
already distinguishes `cron_dead` — the exact case where the daemon must take over waking.
Reuse: `gather_fleet`, `Instance`, `diagnose_root`, `transcript_activity`,
`transcript_age`, `sweep_stale_rate_limit`. No changes anticipated beyond possibly a
survival-flag read helper.

### 3. Shared detector roster (extract from `scripts/dispatch.py`)
`dispatch._DETECTORS` (+ `_NON_HARNESS_DETECTORS`, `_MAINTENANCE_DETECTORS`,
`_detector_is_due`, `_run_detector`) is the SAME set the daemon must now run detached.
Extract the roster + due-gate + runner into a shared module so the two paths (dispatch =
fallback, daemon = primary) never drift on WHICH detectors run or their cadences, and so
`keepalive_stage.daemon_closure` can stage it for the OS daemon.

### 4. `scripts/lib/fleet_inject.py` — actuation (reused)
`build_command_plan` + `fire` type a slash-command / drift line / `[janitor-resume]`
marker into ONE session's own terminal. The wake path builds a per-project message
(finding line OR survival marker), defangs foreign markers, and injects it — `esc_first`
soft (enqueue) by default. Reuse: `build_command_plan`, `build_injection`, `fire`,
`action_to_command`, `is_esc_only`.

### 5. `scripts/lib/global_state.py` — daemon contract + per-project wake dedupe
Reuse `ensure_daemon_running`, `daemon_is_alive`, `acquire_singleton_flock`,
`kill_switch_present`, `maintenance_mode_present`, `global_pause_present`. Add per-project
"wake pending / wake delivered" state (analogous to
`record_fleet_injection` / `fleet_injections_seen` / `clear_fleet_injections`) so a wake
fires ONCE per (project, reason) and is not re-injected on the next 120s scan — with a
dedupe key that does NOT swallow a legitimately-repeated survival wake.

### 6. `scripts/dispatch.py` — demoted to fail-open fallback / thin path
Gate the expensive Phase-2 detector loop so a quiet FALLBACK fire does minimal work,
while KEEPING the survival phases (`_phase_rate_limit_recovery`, `_phase_compact_resume`,
`_phase_clear_resume`, `_phase_heartbeat_renew`) as the backstop when the daemon-wake path
is unavailable. `_resolve_heartbeat_mode` + the resume phases must coexist with
daemon-driven wakes WITHOUT double-firing a resume (the resume flag is single-consumer:
whoever clears it first wins; the other path must no-op). `_defang_foreign_markers` and
`_stamp_resume` semantics must be preserved on both paths.

### 7. OS-keepalive staging — `launchd_keepalive.py` / `keepalive_stage.py` / `keepalive_boot.py`
- `launchd_keepalive.opted_in()` (`CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE`) is the
  fail-open master switch: when the OS keepalive is unavailable/off, the wake loop is
  inert and the per-session cron heartbeat remains the trigger.
- Any new module the wake loop imports MUST be added to `keepalive_stage.daemon_closure`
  (and thus verified by `keepalive_boot.verify_or_restage`) or the OS-spawned daemon
  crash-loops on a torn stage precisely in the all-sessions-down scenario.

### 8. `scripts/hooks/post-compact-resume.py` — survival watch relocation
The PostCompact hook writes `resume-after-compact.flag`. Today the NEXT cron fire emits
`[janitor-resume]`. Under D1, if the cron no longer fires quietly, the DAEMON's wake loop
must watch this per-project flag and inject the resume marker — otherwise post-compact
survival breaks. (No change to the hook itself; the daemon adds a reader.)

### 9. `heartbeat_cadence.py` / `arm_prepare.py` / `skills/janitor-arm/SKILL.md` — cron demotion
For the quiet case the cron demotes to a rare survival-fallback cadence (or, where the OS
keepalive is confirmed active AND the terminal is injectable, a much slower floor). The
tier machinery + `[janitor-renew]` re-arm interaction (`raw_tier`, `commit_tier`,
`should_emit_renew`, `tier_to_cron`; `resolve_cron` / `install_stub` / the desired-cadence
handshake) must be reconciled so the cron stays minimal without dropping renew. The
injected-wake path MUST carry the same marker contract the cron prompt documents
(`~/.claude/rules/janitor-heartbeat-protocol.md`).

### New env knob (fail-open, default preserves current behavior)
`CLAUDE_PLUGIN_OPTION_DAEMON_WAKE_DETECTION_ENABLED` — master opt-in for daemon-owned
wake-detection. Default must preserve today's per-session-cron behavior until the daemon
path is proven; when off/unavailable, the cron heartbeat is the trigger. Reuses existing
`CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE`, `..._SESSION_LIVENESS_ENABLED`,
`..._FLEET_RECOVERY_ENABLED`, `..._DAEMON_SESSION_LIVENESS_INTERVAL` (→ wake latency),
`..._DETECTOR_TIMEOUT`, `..._RATE_LIMIT_FLAG_MAX_AGE_HOURS`, the `heartbeat_cadence` tier
knobs (superseded for the quiet case), `USER_PRESENT_IDLE_S` /
`user_intent.hid_idle_seconds` (typing gate), and `JANITOR_AIMAESTRO_SERVER_CHORES` /
`_STATE` (standalone-vs-harness gate).

## Interdependencies

Shared surfaces with the other three improvements from the 2026-07-23 janitor-shortcomings
critique, and the required ordering:

- **D2 (self-budget).** Shares `dispatch.py::main()` phase pipeline, `_phase_heartbeat_cost`,
  `token_meter.py` (`evaluate_turn_budget`, `tail_turn_usage`, `resolve_context`), and the
  `pre-tool-token-budget` hook. D1 changes WHAT causes a turn; D2 budgets a turn's COST.
  Once D1 moves detectors off-turn, the "heartbeat turn cost" D2 measures on
  `token-meter.jsonl` (via `on-stop-token-meter`) largely disappears for quiet fires — so
  **D1 must land BEFORE D2 re-baselines**, or D2 baselines against soon-to-vanish data.
  Both edit `_resolve_heartbeat_mode` / the phase list → sequence to avoid conflicting
  `main()` edits.
- **D4 (harness self-test).** Shares `harness_backend.py`
  (`backend` / `is_harness_session` / `server_is_alive` / `server_runs_chores` /
  `instance_is_server_owned` / `SERVER_ABSORBED_TASKS`) and
  `state.in_ai_maestro_agent_env`. D1's wake loop keys its WHOLE gate on the same
  standalone-vs-harness discriminator D4 formalizes; D1 MUST reuse D4's exact predicate so
  it never injects into a `server_owned` instance. **Land D4's discriminator first (or
  jointly)**; do not fork a second copy of the gate.
- **D5 (shrink-protocol) — MERGE DECISION.** D5 shares `cold_cache_compact.py`,
  `token_meter.py`, the resume phases (`_maybe_cold_compact_on_rate_limit`,
  `_phase_proactive_idle_compact`, `_phase_compact_resume`), and
  `hooks/post-compact-resume.py`. D5's proactive/cold compaction currently TRIGGERS on a
  cron fire and RESUMES via `resume-after-compact.flag` read on the NEXT cron fire. If D1
  eliminates quiet fires, BOTH ends of D5 must move daemon-side: the daemon must drive the
  proactive-idle shrink decision AND watch the resume-after-compact flag to inject the
  post-compaction wake. **DECISION: D5 does NOT merge wholesale into D1, but D5's
  cron-driven trigger/resume ends DEPEND on D1's daemon wake loop and MUST be implemented
  AFTER D1 (or in a shared follow-up phase).** D1 delivers the daemon wake substrate +
  the resume-flag watch; D5 then relocates `_phase_proactive_idle_compact` /
  `_maybe_cold_compact_on_rate_limit` onto that substrate. Implementing D5 before D1 would
  wire proactive compaction to a trigger D1 is about to remove.
- **Shared actuation across D1/D5.** `fleet_inject.build_command_plan` / `fire` +
  `terminal_trigger.py` (`esc_first` soft/hard) is the single keystroke-send substrate D1
  uses to wake and D5 uses to fire `/compact`. Both must agree on soft-enqueue vs hard-ESC
  and on the `user_intent.hid_idle_seconds` typing gate — settle that contract in D1.
- **Shared roster.** `_DETECTORS` must become a shared module imported by both dispatch
  (fallback) and the new daemon task (primary), and staged by
  `keepalive_stage.daemon_closure`. This extraction is a D1 deliverable that D2/D5 inherit.

**Ordering summary:** D4 discriminator → D1 (this TRDD) → D2 re-baseline + D5 relocation.

## Verification

- **Unit / integration (existing suites, extended):**
  - `tests/test_daemon.py` — main loop, task scheduling, and GUARD ORDERING (kill-switch /
    pause / maintenance / server-owns-host precede the wake task).
  - `tests/test_daemon_session_liveness.py` + `tests/test_session_liveness.py` — the
    fleet-guardian beat + diagnosis→recovery policy the wake task extends.
  - `tests/test_fleet_inject.py` — the injection layer (`build_command_plan` / `fire` /
    `esc_first`) reused for the wake; assert the wake carries ONLY the culprit project's
    findings (TRDD-X92VBFNF channeling) and that foreign markers are defanged.
  - `tests/test_fleet_scan.py` — `gather_fleet` enumeration, `diagnose_root` (`cron_dead`),
    `transcript_activity`, stale-rate-limit sweep.
  - `tests/test_daemon_bulk_lane.py` — the `--run-task` detached child path the wake task
    uses.
  - `tests/test_daemon_maintenance_keepalive.py` + `tests/test_one_daemon_per_host.py` —
    a SURVIVAL wake survives maintenance (like `oauth-rotator-tick`) and the singleton /
    server-owns-host exit is respected.
  - `tests/test_dispatch_phases.py` + `tests/test_dispatch_cadence.py` — the demoted
    fallback path still runs the survival phases and does NOT double-fire a resume when the
    daemon already injected one.
  - `tests/test_post_compact_resume_hook.py` + `tests/test_resume_trigger.py` — post-compact
    + rate-limit resume DO NOT regress when watched daemon-side.
  - `tests/test_launchd_keepalive.py` + `tests/test_keepalive_boot.py` +
    `tests/test_keepalive_stage.py` + `tests/test_daemon_keepalive_entry.py` — the OS
    keepalive exists AND every new wake-loop import is in `daemon_closure` (a staging test
    that fails if an import is missing from the closure).
  - `tests/test_heartbeat_cadence.py` — the cron demotes correctly for the quiet case
    without dropping renew.
  - `tests/test_arm_scripts.py` + `tests/test_dispatcher_stub.py` +
    `tests/test_heartbeat_protocol_rule.py` — the injected wake honors the same marker
    contract the cron prompt documents.

- **Survival-latency proof (spec-mandated "unchanged or better"):** a table-driven test
  comparing, for each survival case, the time-to-wake under (a) today's cron-fire path and
  (b) the daemon-wake path:
  - *rate-limit resume* — daemon must probe reachability BEFORE injecting `[janitor-resume]`
    (replacing the "fire proves API up" invariant); assert the injected turn is not fired
    into a still-limited window. Latency: ≤ the scan cadence (120s default), asserted
    ≤ the cron's own next-fire interval for the same session's armed tier.
  - *post-compact resume* — daemon watches `resume-after-compact.flag`; assert wake within
    one scan cadence of the flag write.
  - *renew (7-day)* — assert the daemon still triggers `[janitor-renew]` before expiry, OR
    the fail-open cron does; never both silently dropped.
  - *un-injectable terminal* — assert the daemon DECLINES and the per-session cron remains
    armed as the only trigger (no silent lost resume).
  - *#J harness* — assert the wake loop is inert (`backend != standalone`) and never injects
    into a `server_owned` instance.

- **Cost proof:** a bounded-daemon test asserting the detached per-project detector fan-out
  stays within `DETECTOR_TIMEOUT` and per-project due-gates, so the daemon itself does not
  become the new starvation source for the 60s survival beats.

## Notes and lessons learned

(none yet)
