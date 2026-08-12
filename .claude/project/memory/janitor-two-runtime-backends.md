---
name: janitor-two-runtime-backends
description: "does the janitor run a daemon inside an ai-maestro agent / why no daemon spawn inside the harness / what is #N standalone vs #J harness mode / where does resume rate-limit compact survival come from inside ai-maestro / can the janitor call the ai-maestro HTTP API directly / why was contextPoisoned blocked / the ai-maestro boundary is the scripts never the API / the feature works standalone but not on a server host / our stamp file is never written / a chore the server claims broke a downstream trigger / rotation happened but nothing reacted / why is this dead only on the ai-maestro host"
ocd: 2026-08-02
lmd: 2026-08-02
metadata:
  node_type: memory
  type: project
  tier: aspect
  functionality: harness-backend-mode
---

# janitor-two-runtime-backends



^ATOM-Y81T-VLC6 [desc:"The two backends: #N standalone (full mode, own daemon) vs #J harness (thin mode, no daemon, delegated to the server) + the actuation-exclusion hands-off rule", keywords: standalone_vs_harness_mode no_daemon_inside_harness actuation_exclusion_server_owned_agents, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

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


^ATOM-A1Q7-Z6HU [desc:"IRON RULE: the ai-maestro boundary is the frozen CLI scripts, never the HTTP API — a missing verb is reported, never bypassed", keywords: iron_rule_ai-maestro_boundary_scripts_only forbidden_to_call_http_api_directly contextPoisoned_blocked_cmd_update_allow_list missing_verb_report_never_bypass, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

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


^ATOM-4GQU-0C9J [desc:"A claimed chore transfers the ACT to the server but not the BREADCRUMB — every janitor feature triggered by our own stamp goes dark on a server-owned host, invisibly", keywords: the_feature_works_standalone_but_not_on_a_server_host our_stamp_file_is_never_written a_chore_the_server_claims_broke_a_downstream_trigger rotation_happened_but_nothing_reacted why_is_this_dead_only_on_the_ai-maestro_host breadcrumb_absent_looks_like_the_event_never_happened, type: project, ocd: 2026-08-12, lmd: 2026-08-12]

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


^ATOM-7Q1V-SGJE [desc:"The server↔janitor data channel: the server WRITES answers into <project>/.janitor/daemon_responses/; the janitor never calls a script and needs no credential", keywords: hibernation.json daemon_responses hibernated_vs_crashed is_an_offline_agent_broken server_pushes_a_file janitor_receives_never_requests staleAfterS, ocd: 2026-08-05, lmd: 2026-08-05]

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



^ATOM-7XL7-5KFU [desc:"Each project reads ONLY its own daemon_responses file — the consumer must respect the boundary, not route around it", keywords: least_privilege_agent_workdir own_record_not_the_roster do_not_read_another_project's_daemon_response compromising_one_agent, ocd: 2026-08-05, lmd: 2026-08-05]

An agent workdir receives that agent's OWN record plus fleet-wide counts, never the roster: the full
map in every workdir would mean compromising any one agent yields every agent's id, name and tmux
session name. Only the ai-maestro install tree gets the roster.

So each project reads ONLY its own file. The janitor dashboard deliberately does NOT read the
install tree's roster on another project's behalf, even though it has filesystem access to it — a
least-privilege boundary is worth nothing if the consumer routes around it using a path it merely
happens to be able to open.


^ATOM-IWDE-4N45 [desc:"How to read a daemon_responses answer: version-check, trust the producer's staleness window, and never render absence as a verdict", keywords: unrecognised_version_treat_as_absent staleAfterS_from_the_producer no_live_answer_is_not_good_news hibernated_is_healthy ts_bool_epoch_1, ocd: 2026-08-05, lmd: 2026-08-05]

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
