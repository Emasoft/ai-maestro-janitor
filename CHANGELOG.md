# Changelog

All notable changes to this project will be documented in this file.

## [0.43.0] - 2026-07-14

### Bug Fixes

- Push /janitor-resume after a compaction so an idle session wakes in seconds, not up to 30 min (TRDD-HI0BGQGJ)
- 4 code-review findings on the fleet-audit + cold-cache work
- Omit required_status_checks when no CI contexts — GitHub 422s an empty array
- The ai-maestro inject channel reported success on spawn, not delivery (TRDD-3VW434Q8)
- The schema migration manufactured the FTS corruption it was meant to fix
- Never type into the user's pane while they are present unless they asked
- Disarmed.flag now requires real human authority (TRDD-RDFWQIFA)
- The two merge gates were mutually unsatisfiable (TRDD-MQBV844P)
- Janitor-github-config-fix had unparseable frontmatter
- Tighten janitor-github-config-fix description under the token limit
- Clear the three --strict NITs blocking the release

### Documentation

- K1RJUYGK shipped in v0.42.0 → column testing; falsification (re-measure) still pending
- Record the self-update bootstrap gap — a fast-updater can't accelerate its own first release
- HI0BGQGJ implemented in 307427a → column testing; falsification of the attended gate verified
- 157OH2D7 implemented in 8bd2949 → column testing
- EUWIHP0G implemented in dc059f3 → column testing
- Refresh the fenced CLAUDE.md project map
- 3VW434Q8 implemented in e7c4624 → column testing; falsification verified
- Add TRDD-RDFWQIFA — disarmed.flag is a forgeable user opt-out
- Record the memgrep FTS-desync corruption, indexed by its symptom
- Add TRDD-MQBV844P — the two merge gates are mutually unsatisfiable
- Add TRDD-CGYMUKO6 — janitor support-ticket system (incident management)
- The issue-code catalog + resume state
- Publish the issue-code catalog as docs/ISSUE-CODES.md
- TRDD-CGYMUKO6 — record the finding that changed the design

### Features

- Fleet-wide GitHub-config audit + on-demand fix skill (TRDD-157OH2D7)
- Cold-cache auto-compact on resume after a >1h idle gap (TRDD-EUWIHP0G)
- Validated, transactional schema migrations — a migration must prove its own output
- The support-ticket core — incident queue + the ownership boundary (TRDD-CGYMUKO6)
- The scheduler + the CLI — dispatch across heartbeats (TRDD-CGYMUKO6)
- The issue-code catalog — one entry point every scanner raises through (TRDD-CGYMUKO6)
- Memgrep emits issue codes; the health detector turns them into work (TRDD-CGYMUKO6)
- Arm the incident queue — the self-heal ledger, the agent, the wiring (TRDD-CGYMUKO6)

### Miscellaneous

- Refresh the fenced CLAUDE.md project map (stale digest)

### Styling

- Apply cargo fmt

