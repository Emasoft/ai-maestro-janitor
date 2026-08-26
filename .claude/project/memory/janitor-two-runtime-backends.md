---
name: janitor-two-runtime-backends
description: "does the janitor run a daemon inside an ai-maestro agent / why no daemon spawn inside the harness / what is #N standalone vs #J harness mode / where does resume rate-limit compact survival come from inside ai-maestro / can the janitor call the ai-maestro HTTP API directly / why was contextPoisoned blocked / the ai-maestro boundary is the scripts never the API / the feature works standalone but not on a server host / our stamp file is never written / a chore the server claims broke a downstream trigger / rotation happened but nothing reacted / why is this dead only on the ai-maestro host / hibernated vs crashed agent how to tell / is an offline agent actually broken / why does the janitor never call an ai-maestro script for status / does the janitor need a credential to read agent status / how does the janitor know a hibernation state without polling"
ocd: 2026-08-02
lmd: 2026-08-02
metadata:
  node_type: memory
  type: project
  tier: aspect
  functionality: harness-backend-mode
---

# janitor-two-runtime-backends



^ATOM-Y81T-VLC6 [desc:"The two backends: #N standalone (full mode, own daemon) vs #J harness (thin mode, no daemon, delegated to the server) + the actuation-exclusion hands-off rule", keywords: standalone_vs_harness_mode no_daemon_inside_harness actuation_exclusion_server_owned_agents does_the_janitor_run_a_daemon_inside_ai-maestro why_no_daemon_spawn_inside_the_harness harness_backend.py_is_the_ssot_for_the_discriminator continuity_delegated_to_the_servers_aimaestro-continuity.sh the_server_is_the_daemon_for_harness_agents unknown_ownership_means_hands_off what_is_the_n_standalone_vs_j_harness_mode fleet_recovery_marks_server-owned_agents_and_never_types_into_their_panes thin_mode_workdir_detectors_only_no_outside-project_writes, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

The SAME plugin branches at runtime on `harness_backend.py` (SSOT; discriminator
`state.in_ai_maestro_agent_env()` — env flags `AIMAESTRO_AGENT`/`THIS_IS_AIMAESTRO`,
fallback `AMP_AGENT_ID`/`AID_AUTH`):

- **#N standalone** (outside ai-maestro): FULL mode — heartbeat + detectors + the global
  daemon, exactly as documented in this file.
- **#J harness** (inside an ai-maestro agent): THIN mode — workdir detectors only; **no
  daemon spawn, no outside-project writes**; Family-A continuity (resume/rate-limit/compact
  survival) is DELEGATED to the server's `aimaestro-continuity.sh` (e.g. `on-stop-failure`
  fires `ensure-resume` via the agent CLI, detached). The SERVER is the daemon for harness
  agents.
- **Actuation exclusion:** the #N daemon's fleet recovery/stop marks server-owned agents
  (`server_owned` diagnosis) and NEVER types into their panes — unknown ⇒ HANDS OFF.


^ATOM-A1Q7-Z6HU [desc:"IRON RULE: the ai-maestro boundary is the frozen CLI scripts, never the HTTP API — a missing verb is reported, never bypassed", keywords: iron_rule_ai-maestro_boundary_scripts_only forbidden_to_call_http_api_directly contextPoisoned_blocked_cmd_update_allow_list missing_verb_report_never_bypass can_the_janitor_call_the_ai-maestro_http_api_directly why_was_contextPoisoned_blocked the_ai-maestro_boundary_is_the_scripts_never_the_api every_interaction_goes_through_the_frozen_cli overloading_an_unrelated_flag_is_a_bypass_in_disguise a_missing_verb_is_a_gap_to_report_not_a_licence_to_bypass every_skill_that_touches_the_boundary_must_say_so no_plugin_element_may_call_api_or_23000_directly, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

- **IRON RULE — the ai-maestro boundary is the SCRIPTS, never the HTTP API** (owner directive
  2026-08-02). Every interaction goes through the frozen CLI (`aimaestro-*.sh`, `amp-*.sh`,
  `aid-*.sh`); no plugin element may call `/api/*` or `:23000` directly, from any surface —
  code, hook, script, skill, or agent. **And every SKILL that touches the boundary must SAY
  so**, not merely avoid the API: a skill that leaves it unstated lets the next agent infer
  the API is fair game. **A missing verb is a gap to REPORT, never a licence to bypass** —
  calling the API, overloading an unrelated flag (`--tags` for a security signal), or dropping
  a side-channel file for the server to poll are one violation in three costumes. Measured
  instance: setting `contextPoisoned` (janitor#167) is blocked precisely here, because
  `cmd_update`'s option allow-list has no such flag — reported to ai-maestro rather than
  worked around.


^ATOM-4GQU-0C9J [desc:"A claimed chore transfers the ACT to the server but not the BREADCRUMB — every janitor feature triggered by our own stamp goes dark on a server-owned host, invisibly", keywords: the_feature_works_standalone_but_not_on_a_server_host our_stamp_file_is_never_written a_chore_the_server_claims_broke_a_downstream_trigger rotation_happened_but_nothing_reacted why_is_this_dead_only_on_the_ai-maestro_host breadcrumb_absent_looks_like_the_event_never_happened a_claimed_chore_transfers_the_act_but_not_the_breadcrumb key_off_an_observable_state_change_never_our_own_stamp what_else_did_we_hang_off_our_own_doing_of_it tests_cannot_catch_this_class_because_both_ends_pass a_changed_live_identity_in_the_beacon_not_a_ts_field the_janitor_stops_performing_the_act_but_keeps_owning_downstream, type: project, ocd: 2026-08-12, lmd: 2026-08-12]

When a live ai-maestro server CLAIMS a chore, the janitor stops PERFORMING the act but keeps
owning everything downstream of it — and any breadcrumb our code writes to signal that act is
then never written. The feature goes dark exactly on the host where the act still happens, and
NOTHING NOTICES, because a missing breadcrumb is indistinguishable from "the event did not
occur". Measured 2026-08-12 on TRDD-UA4FAX67: `rotation-success.ts` (only writer:
`rotator._switch_blob`) was absent while a rotation had demonstrably landed 08-11 10:00:13 —
the server holds `oauth-rotator-tick` here — so the post-rotation pane wake could never fire.
Tests cannot catch this class: they verify both ends, and what breaks is that on this host the
ends are not connected. Same shape as G4BCRUP7's R3 (`fleet-plugins-update` unowned). THE FIX
PATTERN: key off an OBSERVABLE STATE CHANGE both runtimes produce, never off our own
event-stamp — for rotation that is a changed live IDENTITY in the shared beacon, and never its
`ts`, which also advances on age and on a fail-open unknown mtime. Ask of any chore the server
can claim: *what else did we hang off our own doing of it?*

## See also

- [[janitor-architecture]] — the architecture hub this page details the harness-backend split for.


^ATOM-7Q1V-SGJE [desc:"The server↔janitor data channel: the server WRITES answers into <project>/.janitor/daemon_responses/; the janitor never calls a script and needs no credential", keywords: hibernation.json daemon_responses hibernated_vs_crashed is_an_offline_agent_broken server_pushes_a_file janitor_receives_never_requests staleAfterS the_janitor_cannot_observe_hibernation_directly a_pushed_file_needs_no_authorization_at_all the_path_is_never_caller-supplied_realpath-checked strictly_safer_than_a_script_the_janitor_could_call fleet_data_cannot_be_redirected_to_an_outlet, ocd: 2026-08-05, lmd: 2026-08-05]

The janitor cannot observe hibernation: the ai-maestro registry reads `offline` for a hibernated
agent, a crashed one, and one never woken alike. Rather than guess, the dashboard reported NEITHER —
correct, but it left the state unknown. Since janitor#194 the server answers it.

**The channel, and why its shape is the point.** The server WRITES
`<project-root>/.janitor/daemon_responses/hibernation.json` on a ~2 min cadence. The janitor calls
nothing, needs no credential, and executes nothing — it RECEIVES. Agent status is not public data,
so the only party that reads the registry or runs those commands is the daemon integrated into the
server. This is strictly safer than the script the janitor originally asked for (ai-maestro#113): a
command must be authorized on every call, whereas a pushed file needs no authorization at all
because nobody is asking for anything. The path is never caller-supplied — every destination is
derived from the registry and realpath-checked — so fleet data cannot be redirected to an outlet
someone else controls.



^ATOM-7XL7-5KFU [desc:"Each project reads ONLY its own daemon_responses file — the consumer must respect the boundary, not route around it", keywords: least_privilege_agent_workdir own_record_not_the_roster do_not_read_another_project's_daemon_response compromising_one_agent each_project_reads_only_its_own_daemon_responses_file the_full_map_in_every_workdir_would_leak_the_whole_fleet only_the_ai-maestro_install_tree_gets_the_roster a_boundary_is_worth_nothing_if_the_consumer_routes_around_it filesystem_access_is_not_the_same_as_permission compromising_one_agent_should_never_leak_the_whole_fleet each_project_gets_only_its_own_workdir_record fleet-wide_counts_only_never_the_full_roster, ocd: 2026-08-05, lmd: 2026-08-05]

An agent workdir receives that agent's OWN record plus fleet-wide counts, never the roster: the full
map in every workdir would mean compromising any one agent yields every agent's id, name and tmux
session name. Only the ai-maestro install tree gets the roster.

So each project reads ONLY its own file. The janitor dashboard deliberately does NOT read the
install tree's roster on another project's behalf, even though it has filesystem access to it — a
least-privilege boundary is worth nothing if the consumer routes around it using a path it merely
happens to be able to open.


^ATOM-IWDE-4N45 [desc:"How to read a daemon_responses answer: version-check, trust the producer's staleness window, and never render absence as a verdict", keywords: unrecognised_version_treat_as_absent staleAfterS_from_the_producer no_live_answer_is_not_good_news hibernated_is_healthy ts_bool_epoch_1 an_unrecognised_schema_version_is_treated_as_absent staleness_uses_the_producers_published_window_never_a_constant absent_stale_malformed_all_mean_no_live_answer never_render_absence_as_a_verdict_of_healthy_or_broken the_dashboard_omits_the_clause_rather_than_printing_zeros how_to_read_a_daemon_responses_answer_correctly parsing_a_future_schema_with_todays_assumptions_is_a_silent_misread, ocd: 2026-08-05, lmd: 2026-08-05]

`scripts/lib/hibernation.py` (consumed at `16195eb8`) reads the answer under three rules that are
each load-bearing:

- **Version-checked** — an unrecognised `v` is treated as ABSENT, not as data. Parsing a future
  schema with today's assumptions is how a silent misread happens.
- **Staleness uses the PRODUCER's published `staleAfterS`**, never a constant on the janitor side,
  so the server can change cadence without the janitor quietly declaring every answer stale.
- **Absent / stale / malformed all mean NO LIVE ANSWER** — never "the fleet is fine", never "the
  fleet is broken". The dashboard omits the clause rather than printing zeros (zeros read as an
  all-clear), and the session column falls back to what it can observe. Absence is not permission
  to guess.

`hibernated` and `never_woken` are HEALTHY; only `crashed` is a fault. One Python trap worth
remembering: `bool` is an `int` subclass, so a naive isinstance check reads `"ts": true` as epoch 1.

## Notes and lessons learned
