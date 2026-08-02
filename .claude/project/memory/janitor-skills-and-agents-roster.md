---
name: janitor-skills-and-agents-roster
description: "why did janitor-pause disappear / arm disarm is the only switch / what skills does the janitor ship / janitor-compact-context soft vs hard / janitor-reload-skills vs janitor-reload-plugins / what are the two janitor agents / janitor-memory-subconscious-agent vs janitor-security-agent / where do janitor tests and TRDDs live"
ocd: 2026-08-02
lmd: 2026-08-02
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: skills-and-agents-roster
---

# janitor-skills-and-agents-roster


^ATOM-NH7H-YPR8 [desc:"Agents(2), Tests, and Design docs sections verbatim: the two single-curator agents (memory + security), the pytest test suite conventions, and where TRDDs live", keywords: the_two_agents_janitor-memory-subconscious-agent_janitor-security-agent single_curator_agent_per_domain tests_directory_pytest_per_pattern_lib design_docs_TRDDs_location, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

**Agents (`agents/`, 2)** — the TWO single-curator agents, each ONE agent that loads
many per-task SKILLS (never one-agent-per-task), runs in its OWN context, returns one
line + a report. `janitor-memory-subconscious-agent` (Wikimem editorial: consolidate/
split/conflict/repair/atomize/harvest; auto-dispatched by `memory-maintenance` via bare
`[janitor-memory-*]` markers). `janitor-security-agent` (TRDD-f12cae1a — ALL 8 security
skills, DETECT + FIX fail-safe; the security detectors SUGGEST it via
`security_helpers.security_agent_hint()` — a visible hint, NOT a silent marker, since
security fixes have real blast radius; opt out `CLAUDE_PLUGIN_OPTION_SECURITY_AGENT_HINT=false`).
Memory agent `model: sonnet` (USER cost decision 2026-06-30), security agent `model: opus`; both `effort: high`.

**Tests (`tests/`)** — pytest; one `test_*_patterns.py` per pattern lib + core tests
(`test_marketplace_lock`, `test_rules_installer`, `test_marketplace_refresh_daemon_stale`, …).
Real, no mocks; isolate global state via `JANITOR_GLOBAL_STATE_DIR` and `HOME`/`CLAUDE_PROJECT_DIR`.

**Design docs (`design/tasks/`)** — TRDDs (see `~/.claude/rules/trdd-design-tasks.md`).


^ATOM-1B0M-ZBXT [desc:"Skills part 1: janitor-arm/disarm (local cron true-stop), janitor-global-disarm/arm (machine-wide) — arm/disarm is the only switch", keywords: arm_disarm_only_switch janitor-global-disarm_janitor-global-arm kill_switch_makes_daemon_exit, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

**Skills (`skills/`)** — control surface: `janitor-arm` ↔ `janitor-disarm` (local cron
true-stop), `janitor-global-disarm` ↔ `janitor-global-arm` (machine-wide, backed by
`scripts/global_control_cli.py disarm|arm|reload-skills|status` — kill-switch=disarm makes
the daemon EXIT). **ARM/DISARM IS THE ONLY SWITCH** (owner directive 2026-07-31, *"remove
the very option of disabling the janitor features"*). PAUSE (local + global) went in
v0.67.0 and MAINTENANCE MODE (local + global) with it: each suspended the janitor while
leaving the cron firing and the daemon resident, i.e. indistinguishable from a healthy
fleet from the outside — the same silent-disable shape as the `keep-going-off` incident.
Maintenance was the more defensible of the two (a fire re-reads context at the 0.1× READ
rate ≈ 1/10 the 1.0× REWRITE a dead cache costs, so a do-nothing fire looked like the cheap
way to stay warm) and it is gone for exactly the same reason. Stale `global-pause.flag` /
`maintenance-mode.flag` / `.janitor/state/{paused,maintenance-mode}` are INERT and swept
(`state.RETIRED_SENTINELS`, swept by dispatch each fire AND by every arm); the retired CLI
verbs are REJECTED, never accepted as no-ops. TWO heartbeat modes


^ATOM-8M9J-3N0R [desc:"Skills part 2: why PAUSE and MAINTENANCE MODE were retired in v0.67.0 (indistinguishable from a healthy fleet from the outside)", keywords: pause_maintenance_mode_retired_v0.67.0 silent_disable_shape_same_as_keep-going-off stale_flags_inert_and_swept, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

(`dispatch._resolve_heartbeat_mode`): FULL (fire + due chores + daemon) and STOP
(self-disarm). A global stop TRULY STOPS the heartbeat (free), not just silences it
(TRDD-RQ9FIFX6): the flag makes `dispatch.py` emit a bare `[janitor-self-disarm]` marker →
the session runs `/janitor-disarm` → the cron DELETES ITSELF, because a cron FIRE is a full
Claude turn that re-reads ~618k cached tokens (billed at the 0.1× cache-read rate, NOT free)
whether or not detectors run — only NOT firing costs zero. **Cost is answered by the SLOW
cadence tier (fewer fires, same work) and by `_phase_self_cost_alarm`, which prints one
drift line naming this project's own 7d heartbeat spend past `heartbeat_self_budget` and
actuates NOTHING** — it replaced the TRDD-ZCODD6YS two-rung throttle (cadence cap → auto
LOCAL maintenance), reverted by the same "never self-disable" ruling.


^ATOM-5VTX-06LU [desc:"Skills part 3: the two heartbeat modes (FULL/STOP) and why a global stop deletes the cron instead of merely silencing it", keywords: two_heartbeat_modes_full_stop global_stop_truly_stops_the_heartbeat_free cron_fire_rereads_618k_cached_tokens, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

**The never-stop continue-nudge is UNCONDITIONAL** — `dispatch._phase_keep_going_nudge()`
fires on EVERY heartbeat, takes no mode, and has one wording. Its opt-in flag, its
`/janitor-keep-going off` sentinel and the
`keep_going_default` knob were all REMOVED in v0.67.0 (owner directive 2026-07-31, *"remove the
very option of disabling the janitor features"*): a host was found carrying
`.janitor/state/keep-going-off` dated 14 days back, so every fire had correctly done nothing and
looked healthy. The ONE remaining skip is time-bounded and self-clearing — the single fire right
after a `[janitor-resume]` cue, which already said "continue" and carried the directive
(`_keep_going_muted_by_recent_resume`); that is a de-duplicator, not a mute.
Rollout caveat: crons armed BEFORE this shipped don't self-disarm (the cron prompt is baked at
arm-time) → one-time manual `/janitor-disarm`. `janitor-memory-record-recent`
(user-invoked Wikimem harvest of recent changes — active counterpart of memorize-nudge).
`janitor-supply-chain-watcher`, `janitor-dependabot-doctor`,
`janitor-credential-window-audit`, `janitor-github-workflow-doctor`,
`janitor-github-workflow-create`, `janitor-fork-pr-cache-audit`,
(the four `janitor-issues-watch-{on,off}` / `janitor-github-issues-monitor-{on,off}` skills were
DELETED on 2026-08-02 by owner order — both features are always-on chores, so the `-on` pair


^ATOM-AW27-24YV [desc:"Skills part 4: the unconditional keep-going nudge, and the skill roster (memory-record-recent, supply-chain-watcher, dependabot-doctor, credential-window-audit, github-workflow-doctor/create, fork-pr-", keywords: keep_going_nudge_unconditional_never_disable janitor-memory-record-recent_supply-chain-watcher_dependabot-doctor deleted_issues-watch_skills_2026-08-02, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

had nothing to enable and the `-off` pair was exactly the per-feature silent disable the
2026-07-31 directive removed; arm/disarm is the only switch, plus the two config knobs),
`janitor-compact-context` (agent-invocable self-compact + auto-resume; backed by
`scripts/compact_trigger.py`; SOFT/enqueue by default since TRDD-0GPQROC1 — `/compact`
runs when the turn ends; `--hard` = ESC-interrupt for emergencies (the ≥85% enforcement
hook passes it), `--handoff` = run `/janitor-write-handoff` first — combinable —
TRDD-LQU7OXXV), `janitor-write-handoff` (rich agent-authored handoff to
`.janitor/state/agent-handoff.md`, the OPT-IN semantic complement to the always-on
zero-cost `pre-compact-handoff.py`; `--then-compact` chains to `/compact`),
`janitor-reload-plugins` (→ `/reload-plugins --force`; soft default, `--hard`),
`janitor-reload-skills`
(→ CC's `/reload-skills` for STANDALONE non-plugin skills/commands at local/project/user
scope — `/reload-plugins` only reloads plugin-bundled ones; backed by
`scripts/reload_skills_trigger.py`; soft default, `--hard`) ↔ `janitor-global-reload-skills`
(machine-wide:
`global_control_cli.py reload-skills` stamps a `skills-reload-needed.flag` generation that
`dispatch.py _phase_skills_reload` emits `[janitor-reload-skills]` for once-per-session,
mirroring the `[janitor-reload]` path — TRDD-LQU7OXXV). The self-trigger commands share
`scripts/lib/terminal_trigger.py`, which parameterizes `esc_first` (hard=ESC-interrupt /


^ATOM-3VBQ-VF95 [desc:"Skills part 5: compact-context/write-handoff/reload-plugins/reload-skills and the shared terminal_trigger soft-injection default", keywords: janitor-compact-context_soft_hard janitor-write-handoff_janitor-reload-plugins_janitor-reload-skills terminal_trigger_soft_injection_default_esc_first, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

soft=enqueue) + multi-command sends — the substrate TRDD-ME8V2YJF reuses for daemon-driven
fleet injection. **Injection is SOFT by default fleet-wide (TRDD-0GPQROC1):** the three
self-triggers enqueue, `_fire_fleet_stop` types stop commands without ESC, gentle recovery
rungs ESC only a `frozen` target (`fleet_recovery.injection_is_hard`), and
`fleet_inject.build_command_plan` honors `esc_first` on EVERY channel (tmux/wtype/xdotool
included — they used to always ESC).

## Governed by

- [[janitor-architecture]] — the architecture hub; this page is the detailed roster
  behind its abbreviated Skills summary.

## Notes and lessons learned
