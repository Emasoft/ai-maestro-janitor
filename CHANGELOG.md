# Changelog

All notable changes to this project will be documented in this file.

## [0.44.1] - 2026-07-15

### Bug Fixes

- A retried ticket was in the queue AND the archive (TRDD-CGYMUKO6)
- The checklist told the agent to forge the flag the guard exists to gate
- Guard the ≥85% context hardstop against CC 2.1.208's false 100%; doc the 2.1.207 plugin-option scope break
- Heartbeat-filter the anomaly detector + spike threshold; drop the false durable narrative
- Exclude the janitor's own agents from the FAST probe (TRDD-CI6ZTNB9)
- Stop extract_lessons at an atom marker (TRDD-MADJ00KA)
- _body_minus_lessons fails loud on a multi-page concatenation (TRDD-842PBES7)
- Pin allow-ALL (-A) ACL on slot-token keychain writes (TRDD-EQJPPZ2L)
- Set keychain ACL only at CREATE, data-only UPDATE thereafter (TRDD-EQJPPZ2L)
- Self-healing keychain-denied latch (half-open circuit breaker) (TRDD-EQJPPZ2L)

### Documentation

- Refresh the fenced project map (the ticket system's new modules)
- TRDD-CGYMUKO6 — the CLI had no tests, and that is where the bug was
- The tool-call cost law, and why the cadence's own re-arm is billed
- A cache write costs 2x, not 1.25x — the main agent runs a 1h TTL
- Items 2, 3, 4 done; record the grep-as-proof and moving-failure lessons
- Add TRDD-CI6ZTNB9, TRDD-MADJ00KA, TRDD-842PBES7 — 3 verified issues from the GitHub triage
- Add TRDD-EQJPPZ2L — rotator keychain WRITE triggers an ACL prompt (the recurring rotation-death root cause)
- EQJPPZ2L part 1 landed (fa46a49) + correct the fix target
- EQJPPZ2L definitive root cause — ACL flag on -U update prompts (SecKeychainItemSetAccess)
- EQJPPZ2L code fix landed (1cedf28) — items 1+2 done; login validation gated on user
- EQJPPZ2L — rotation GO-LIVE, validated on the real login keychain (TRDD-EQJPPZ2L)
- Clear publish gate — TRDD list-marker NIT (#113) + janitor-arm TOC embed MINOR (TRDD-EQJPPZ2L)

### Features

- Log every turn, not just heartbeats — the arm was unmeasurable (TRDD-DLI76AUC #4)

### Performance

- The re-arm was six billed tool calls, not a config write (TRDD-DLI76AUC)

