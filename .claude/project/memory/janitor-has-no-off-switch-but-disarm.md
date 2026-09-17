---
name: janitor-has-no-off-switch-but-disarm
description: "can I add a pause / quiet mode / temporary silence to the janitor / is there a way to suspend the heartbeat for a while without disarming / why did the janitor-pause command disappear / where did janitor-keep-going off go / is there a per-feature off switch / why does disarm delete the cron but pause did not / a suspended fleet looked exactly like a healthy one / keep-going-off flag found stale 14 days later / how to silence a noisy or expensive heartbeat / can I add a config knob that silences a guard / what are hard_restart_enabled fleet_stop_enabled issues-watch opt-in flags / does disarm survive being mistaken for a working session / why was maintenance mode removed in v0.67.0 / a guard that can be silenced invisibly is not a guard"
ocd: 2026-07-31
lmd: 2026-09-17
metadata:
  node_type: memory
  type: project
  tier: aspect
publish-globally: false
---

^PSYPI8R4 [desc:"ARM/DISARM is the janitor's only switch; as of v1.0.0 it is permanently ON in every armed session, the sole other off-path being automatic handoff of daemon chores to a live ai-maestro server", keywords:can_i_add_a_pause_or_quiet_mode_to_the_janitor is_there_a_way_to_suspend_the_heartbeat is_there_a_per_feature_off_switch arm_disarm_only_switch harness_backend_server_runs_chores, ocd:2026-07-31, lmd:2026-07-31]
**ARM / DISARM is the ONLY switch. Do not add a second one.** As of v1.0.0 the janitor is
permanently ON in every armed session; the only other sanctioned off-path is the automatic
handoff of daemon chores to a live ai-maestro server (`harness_backend.server_runs_chores`).

^TFVYRPTF [desc:"why disarm survives and pause/keep-going-off did not: those left the cron firing and daemon resident doing nothing, so a suspended fleet looked healthy; disarm deletes the cron so it can't look active", keywords:why_did_janitor_pause_command_disappear why_does_disarm_delete_the_cron_but_pause_did_not a_suspended_fleet_looked_exactly_like_a_healthy_one is_janitor_running_vs_is_janitor_doing_anything, ocd:2026-07-31, lmd:2026-07-31]
**Why:** the guarantee had inverted. "Is the janitor running?" and "is the janitor doing
anything?" were different questions with different answers, and nothing surfaced the gap.
`/janitor-pause` left the cron firing and the daemon resident while doing nothing — from a
process list, a cron list, or a daemon heartbeat, a suspended fleet looked exactly like a
healthy one. Same for `keep-going-off`. [^1] Disarm survives because it is the opposite: it
deletes the cron, so a disarmed session cannot be mistaken for a working one.

^0Z9K435Z [desc:"how to apply: refuse any request for a temporary quiet mode, per-feature off switch, or silenceable guard knob, and offer disarm or a cadence change instead; a silenceable guard is not a guard", keywords:how_to_silence_a_noisy_or_expensive_heartbeat can_i_add_a_config_knob_that_silences_a_guard a_guard_that_can_be_silenced_invisibly_is_not_a_guard cost_pressure_answered_by_drift_line_and_slow_cadence, ocd:2026-07-31, lmd:2026-07-31]
**How to apply:** when asked for a "temporary quiet mode", a "suspend for an hour", a
per-feature `*-off`, or a config knob that silences a guard — refuse and offer `disarm`
(or a cadence change, which slows fires without stopping work). A guard that can be
silenced invisibly is not a guard. Cost pressure is answered by a drift line naming the
spend and by the SLOW cadence tier, never by switching detectors off.

^ZMK6TA6B [desc:"opt-IN switches for genuinely dangerous extra capability are kept, distinct from an off-switch: hard_restart_enabled, fleet_stop_enabled, issues-watch ARM — they do not disable existing work", keywords:what_are_hard_restart_enabled_fleet_stop_enabled_issues_watch_flags do_opt_in_capability_flags_disable_existing_work kills_claude_processes_types_into_other_panes_notification_firehose, ocd:2026-07-31, lmd:2026-07-31]
Opt-IN switches for genuinely dangerous EXTRA capability are a different thing and are
kept: `hard_restart_enabled` (kills claude processes), `fleet_stop_enabled` (types into
other panes), `issues-watch` (a notification firehose). Those ARM capability; they do not
disable existing work. See [[janitor-fleet-control-plane]].

## See also

- [[janitor-skills-and-agents-roster]] — the same PAUSE retirement from the SKILLS side: which
  commands exist today, and why `/janitor-pause` and maintenance mode were removed in v0.67.0.
  This page answers "can I quiet the janitor" (no — `disarm` is the switch); that page answers
  "where did `janitor-pause` go". The two were flagged as a CONFLICT candidate by
  `memory-librarian` and are not one — they agree on every fact and were merely unlinked.

## Notes and lessons learned

[^1]: [id:ATOM-NOSW-1TCH, status:valid, keywords:"sticky_sentinel silent_disable keep-going-off janitor_did_nothing_for_days quiet_heartbeat_looked_healthy", ocd:2026-07-31, lmd:2026-07-31]
  DO NOT ship an off-switch whose ON-state is invisible, BECAUSE `.janitor/state/keep-going-off`
  was found on two hosts dated 14 days back — every heartbeat fired, correctly did nothing, and
  read as healthy. DO make any stop delete the thing that fires, so silence is observable.

[^2]: [id:ATOM-NOSW-9RMV, status:valid, keywords:"retired_flag_still_on_disk migration_inert_sweep upgrade_left_machine_suspended", ocd:2026-07-31, lmd:2026-07-31]
  DO NOT merely delete a control flag's writer, BECAUSE hosts still carry the flag and the
  lever to lift it is now gone — the upgrade would strand them suspended forever. DO make the
  retired flag INERT and sweep it (arm clears `global-pause.flag`; dispatch unlinks `paused`),
  and invert its tests to assert it has no effect rather than deleting them.

[^3]: [id:ATOM-NOSW-4KPT, status:valid, keywords:"nudge_text_named_its_own_off_lever agent_ran_it_while_blocked issue_74", ocd:2026-07-31, lmd:2026-07-31]
  DO NOT let a guard's own message name a command that disables it, BECAUSE issue #74 showed
  sessions running `/janitor-keep-going off` while merely BLOCKED ON A HUMAN DECISION — exactly
  when the guard matters most. DO word the nudge so "say so briefly and stop" is the whole
  correct response.
