---
name: janitor-two-runtime-backends
description: "does the janitor run a daemon inside an ai-maestro agent / why no daemon spawn inside the harness / what is #N standalone vs #J harness mode / where does resume rate-limit compact survival come from inside ai-maestro / can the janitor call the ai-maestro HTTP API directly / why was contextPoisoned blocked / the ai-maestro boundary is the scripts never the API"
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

## See also

- [[janitor-architecture]] — the architecture hub this page details the harness-backend split for.

## Notes and lessons learned
