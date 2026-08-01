---
name: janitor-per-project-channeling
description: "can a session/agent see or be told about another project's findings — fleet summary line leaked other repos' drift into every session / where do findings about a repo with no open session go / cross-project notification data exfiltration"
ocd: 2026-07-17
lmd: 2026-07-17
metadata:
  node_type: memory
  type: project
  tier: aspect
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
the daemon's notification channel ([[TRDD-4649ZLE0]] design) — never through another
project's session. The daemon may GATHER fleet-wide (single-writer, issue #7); it may never
BROADCAST fleet-wide into agent contexts.

**Where it is enforced:** `github_config_audit.summarize_for_slug` + `payload_for_slug`
(fleet-aggregate `summarize` deleted); `fleet-github-config` detector (own slug or silent,
own-repo dedupe digest); `_propose_for_this_repo` (was already correct). The same invariant
was communicated to ai-maestro (janitor#100) as binding on the server's daemon-function.

## Applies to

- [[TRDD-4649ZLE0]] — human-notification channel (per-project escalation rule)
- `scripts/detectors/fleet-github-config.py`, `scripts/lib/github_config_audit.py`

See also [[janitor-daemon-bulk-lane]] — the other v0.50.0-era daemon invariant (bulk-lane
serialization, a sibling concern, not governed by this one).

## Notes and lessons learned

[^1]: [id:ATOM-XPRJ-MEM1, status:valid, keywords:"fleet summary counts leaked every session cross project drift line notified other repos", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT surface fleet aggregates ("N/M repos drifted") in a per-session line, BECAUSE even
  bare counts pull the wrong agent toward other repos' problems and normalize a cross-project
  fix pointer. DO emit only the firing project's findings, or nothing.
