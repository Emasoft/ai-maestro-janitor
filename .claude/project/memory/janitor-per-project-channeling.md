---
name: janitor-per-project-channeling
description: "can a session/agent see or be told about another project's findings — fleet summary line leaked other repos' drift into every session / where do findings about a repo with no open session go / cross-project notification data exfiltration / an automatic surface leaked another project's data / agents keep turning global maintenance back on by themselves / why did I see a finding for a repo I have no session in / can a heartbeat drift line mention another repo / does window-burn-rate alarm outside its own project / fleet-wide aggregates in a per-session line are forbidden / what commands are allowed to be machine-wide / why is the context-advisory default 80 percent not 85 / token telemetry per-project channeling invariant / a fleet aggregate leaked cross-project counts into a session / agents must never act on another project's workdir or git / the daemon may gather fleet-wide but never broadcast fleet-wide / can other agents' repo problems leak into my session"
ocd: 2026-07-17
lmd: 2026-07-17
metadata:
  node_type: memory
  type: project
  tier: aspect
publish-globally: false
---

**THE INVARIANT (USER directive 2026-07-17, TRDD-X92VBFNF):** an AUTOMATIC surface
(heartbeat drift line, detector output, injected nudge, proposal TRDD, notification) may
carry information about EXACTLY the project it fires in — never another project's findings,
names, or aggregate counts that include them. Four independent reasons: wrong skills; agents
are FORBIDDEN from acting on other agents' workdirs/gits/repos; token-budget contamination
breaks the division of responsibilities; data exfiltration into projects with weaker
(possibly zero) protections. Only EXPLICIT HUMAN commands (`/janitor-show-global-status`,
`/janitor-github-config-fix --all`) may be machine-wide. [^1]

**Routing consequence:** findings about a project with NO live session go to the HUMAN via
the daemon's notification channel (TRDD-4649ZLE0 design) — never through another
project's session. The daemon may GATHER fleet-wide (single-writer, issue #7); it may never
BROADCAST fleet-wide into agent contexts.

**Where it is enforced:** `github_config_audit.summarize_for_slug` + `payload_for_slug`
(fleet-aggregate `summarize` deleted); `fleet-github-config` detector (own slug or silent,
own-repo dedupe digest); `_propose_for_this_repo` (was already correct). The same invariant
was communicated to ai-maestro (janitor#100) as binding on the server's daemon-function.

## Applies to

- TRDD-4649ZLE0 — human-notification channel (per-project escalation rule)
- `scripts/detectors/fleet-github-config.py`, `scripts/lib/github_config_audit.py`

See also [[janitor-daemon-bulk-lane]] — the other v0.50.0-era daemon invariant (bulk-lane
serialization, a sibling concern, not governed by this one).


^ATOM-IGW8-NJLC [desc:"Per-project channeling ALSO applies to token telemetry: window-burn-rate alarms only inside the culprit project, and the 80% context-advisory default sits one runway band below the 85% enforcement", keywords: token_telemetry_per_project_only window_burn_rate_culprit_project_only context_advisory_default_80_percent one_runway_band_below_enforcement does_per-project_channeling_apply_to_token_telemetry_too unattributable_burn_trips_stay_silent_everywhere why_is_the_advisory_band_below_the_enforcement_band CC_harness_covers_the_mid_band fleet-wide_views_exist_only_behind_explicit_human_commands per-project_channeling_invariant_TRDD-X92VBFNF does_token_telemetry_leak_across_projects_too findings_about_a_repo_with_no_open_session_go_to_the_human, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

- **Per-project channeling invariant (TRDD-X92VBFNF, security):** any AUTOMATIC surface
  carries ONLY the firing project's data — never another project's findings, names, or
  aggregate counts. Fleet-wide views exist only behind explicit human commands. TOKEN
  TELEMETRY included: `window-burn-rate` alarms only inside the CULPRIT project's own
  sessions (unattributable trips silent everywhere); the context-advisory default is 80%
  (one runway band below the 85% enforcement — the CC harness covers the mid band).

## Notes and lessons learned

[^1]: [id:ATOM-XPRJ-MEM1, status:valid, keywords:"fleet summary counts leaked every session cross project drift line notified other repos", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT surface fleet aggregates ("N/M repos drifted") in a per-session line, BECAUSE even
  bare counts pull the wrong agent toward other repos' problems and normalize a cross-project
  fix pointer. DO emit only the firing project's findings, or nothing.
