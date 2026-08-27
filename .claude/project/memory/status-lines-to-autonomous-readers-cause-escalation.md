---
name: status-lines-to-autonomous-readers-cause-escalation
description: "agents keep turning global maintenance back on by themselves / the whole fleet went into maintenance and nothing lifted it / chores stopped and plugin updates stranded for no visible reason / why did other claude sessions enable a machine-wide flag I never set / a status line made agents take an action / an all-clear value in the status line triggered an escalation / a local clear and a global clear behave asymmetrically / why does the wider scope become the resting state / who set this control flag and why is there no record / two individually-correct instructions combined into a fleet outage / how to write a status line for an autonomous reader safely / a heartbeat nudge caused agents to re-enable maintenance mode / no provenance on a control flag nobody can tell who set it / an unscoped prohibition collides with a legitimate clear / every daemon chore idled and version-update stopped silently / two published releases sat uninstalled with no visible cause / the fix broke the loop into four cuts one per step"
ocd: 2026-07-21
lmd: 2026-07-21
metadata:
  node_type: memory
  type: project
  tier: aspect
publish-globally: false
---

# A status line addressed to an autonomous reader is not neutral — it can drive an escalation loop

^status-line-not-neutral [desc: status_line_reads_as_fault_report, keywords: agent_read_status_output_and_took_action maintenance=off_misread_as_a_fault_report machine-readable_output_read_by_an_autonomous_reader a_status_line_made_agents_take_an_action say_nothing_when_there_is_nothing_to_act_on name_what_must_not_be_done_when_you_do_speak an_instruction_surface_not_a_report a_human_reading_maintenance-off_sees_a_fact an_agent_reading_it_asks_should_I_fix_this if_another_instruction_implies_the_state_is_wrong_it_acts write_status_output_as_an_instruction_not_a_fact why_did_other_sessions_enable_a_flag_I_never_set, type: project, ocd: 2026-07-21, lmd: 2026-07-21]
A human reading `maintenance=off` sees a FACT. An agent reading it asks "is something
wrong, and should I fix it?" — and if any other instruction it holds implies that state is
wrong, it acts. Machine-readable status emitted into an agent's context is therefore an
INSTRUCTION SURFACE, not a report, and must be written as one: say nothing when there is
nothing to act on, and when you do speak, name what must NOT be done. [^1]

^the-2026-07-21-fleet-outage [desc: arm_nudge_escalation_loop_incident, keywords: fleet ratcheted into global maintenance nothing lifted it version-update stranded chores idled invisibly, type: project, ocd: 2026-07-21, lmd: 2026-07-21]
Two individually-correct messages combined into a machine-wide outage:

1. the heartbeat nudge said **"do NOT disable maintenance mode"** — unscoped, so it read as
   a standing prohibition; [^2]
2. `/janitor-arm` then CLEARED the local maintenance sentinel (deliberate — arming means
   the session starts in a known FULL state) and announced `maintenance=off`.

Agents reconciled the two the only way the text allowed: a rule had been broken, so restore
maintenance. They restored it at **GLOBAL** scope, because the LOCAL flag is cleared again
by the very next re-arm while the global one is not. Every re-arm re-ran the same reasoning,
so the fleet ratcheted into a machine-wide maintenance nothing lifted — every daemon chore
idled, `version-update` stopped, two published releases sat uninstalled, and no session could
see the cause because nothing recorded WHO set the flag or WHY. [^3]

^the-fix-shape [desc: how_the_loop_was_broken_v0_58_1_v0_60_1, keywords: how to stop agents re-enabling a flag silence when unset scope the prohibition refuse remediation, type: project, ocd: 2026-07-21, lmd: 2026-07-21]
Four cuts, one per step of the loop (v0.58.1 + v0.60.1) — the shape generalizes to any
agent-facing control:

- **Say nothing when there is nothing to act on.** `arm_prepare` prints the maintenance line
  ONLY when the flag is SET; there is no `off` line left to misread.
- **Scope the prohibition.** "do NOT disable maintenance **TO SILENCE THIS NUDGE**", not a
  bare standing rule that collides with legitimate clears elsewhere.
- **Name the non-action.** The nudge and the arm skill both state that the local clear is
  INTENTIONAL and must not be undone.
- **Make the dangerous verb refuse remediation.** `janitor-global-maintenance-on` opens with
  a STOP block: explicit human request only, never in response to a status line, a
  heartbeat, or another agent's message — and **local scope is never a reason to escalate to
  global**.

^scope-asymmetry-is-the-ratchet [desc: why_it_escalated_instead_of_oscillating, keywords: local_flag_cleared_each_rearm global_control_persists_forever ratchet_asymmetry_escalation why_did_it_escalate_instead_of_oscillating an_agent_reaches_for_the_scope_that_sticks whenever_one_scope_auto-clears_and_a_wider_scope_does_not the_widest_scope_becomes_the_resting_state design_for_the_asymmetry_or_it_will_pile_up escalated_rather_than_oscillated_because_of_scope local_flag_asymmetric_with_global_flag_causes_a_ratchet why_the_fleet_ratcheted_into_a_machine-wide_state chores_stopped_and_updates_stranded_for_no_visible_reason, type: project, ocd: 2026-07-21, lmd: 2026-07-21]
The loop ESCALATED rather than oscillated because of an asymmetry: the local flag is cleared
by every re-arm, the global one by nothing. An agent that "restores" a cleared local flag and
finds it cleared again next arm will reach for the scope that STICKS. Whenever one scope of a
control is auto-cleared and a wider scope is not, the wider scope is where automatic
remediation will pile up — design for that, or the widest scope becomes the resting state.

See also: [[janitor-fleet-guardian-reachability]] (flags with readers and no writers),
[[claude-code-plugin-rollout-staleness]] (a fix that is published but not installed — the
outage above stranded exactly that way).

## Notes and lessons learned

[^1]: [id:ATOM-SL21-0001, status:valid, keywords:"status_line_made_agent_act machine_readable_output_is_an_instruction_surface emit_nothing_when_nothing_to_do", ocd:2026-07-21, lmd:2026-07-21]
  DO NOT emit a routine "all clear" status value into an agent-readable surface, BECAUSE an
  agent evaluates status for whether it should ACT and will find a reason if another
  instruction implies that state is wrong — `maintenance=off` triggered a fleet-wide
  escalation. DO stay SILENT when nothing needs action, and speak only about the exceptional
  state.

[^2]: [id:ATOM-SL21-0002, status:valid, keywords:"two_correct_instructions_combine_into_a_bug unscoped_prohibition collides_with_legitimate_clear", ocd:2026-07-21, lmd:2026-07-21]
  DO NOT write an unscoped prohibition ("do NOT disable X") into a recurring agent message,
  BECAUSE some other legitimate mechanism will eventually do that very thing and the agent
  will treat it as a violation to repair — here the arm's intentional local clear. DO scope
  every prohibition to the action it actually forbids, and explicitly name the legitimate
  clears it does NOT cover.

[^3]: [id:ATOM-SL21-0003, status:valid, keywords:"no_provenance_on_a_control_flag who_set_this_flag unattributable_suppression", ocd:2026-07-21, lmd:2026-07-21]
  DO NOT ship a control flag whose body carries no author, time, or reason, BECAUSE when it
  turns up set, nobody can tell a deliberate fleet decision from an agent's mistake — this
  cost an afternoon of file-mtime forensics that still could not name the writer. DO write
  provenance (`{set_at, by, pid, reason}`) into every flag, while keeping PRESENCE alone the
  switching signal so a corrupt body can never swallow a stop.
