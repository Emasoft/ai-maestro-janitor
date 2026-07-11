# Changelog

All notable changes to this project will be documented in this file.

## [0.40.0] - 2026-07-11

### Bug Fixes

- ESC-interrupt a FROZEN target so a machine-wide stop actually lands
- The resume FAST signals were unreachable — stamp last-resume.ts
- The keychain denied-latch was still writing to the LEGACY global-state dir
- Refuse to stage the daemon closure over a plugin SOURCE checkout (TRDD-RYZCVVKA)
- The roots SSOT must honor CLAUDE_PLUGIN_OPTION_TRDD_PATH
- SessionStart hook died on import 2026-06-20 — restore it, and prove hooks run
- The write guard failed the suite for the LIVE daemon's own work (S1f)
- Clear the 3 CPV strict gates the guard/scope work tripped

### Documentation

- Add TRDD-0GPQROC1 — soft-by-default command injection
- Record TRDD-0GPQROC1 implementation commit + test pass
- Add TRDD-0QQX9H0G — TTL-aware dynamically-tiered heartbeat cadence (#83)
- Close out 0GPQROC1 + 0QQX9H0G; open the agentlensPro adoption trio
- Close 7 shipped-but-open TRDDs — board drift, not unfinished work
- P4 answered by measurement; YXY992BN superseded by agentlensPro
- TRDD-2KQQAEPP → complete (551531c)
- ULEGRT01 blocked on publishing 7ceab3f — the gate caught a real bug
- VQ4LX7ND part-2 silence fixed; file TRDD-RYZCVVKA — working tree clobbered by the cached closure
- RYZCVVKA — write path found and closed; suite exonerated by instrumentation; invoker still unattributed
- YRPUSIFY P2 shipped — always-loaded floor 270,596 -> 200,259 B (-26%)
- RYZCVVKA attributed — and retract the false "suite exonerated" claim
- Record the RYZCVVKA recurrence on the keepalive-isolation wiki page
- Refresh the fenced project map (picks up the iTerm TCC detectors)
- TRDD spec gains LOCAL scope, and the id-collision check stops infinite-looping
- Record the two-import-conventions trap that killed the SessionStart hook

### Features

- Soft-by-default — commands enqueue at the turn boundary (TRDD-0GPQROC1)
- TTL-aware dynamically-tiered cadence — 6x cheaper idle, zero recovery regression (TRDD-0QQX9H0G, #83)
- Notify main Claude of new GitHub issues and comments (TRDD-2KQQAEPP)
- Session-start breadcrumb + stop the manifest lying about two default-ON hooks (TRDD-98ISATJZ)
- Verify-before-scrub — never destroy cookies we cannot prove we can restore (TRDD-dfc0959a)
- Scope-migration --apply — publish a reviewed plan, and refuse everything else (TRDD-47df698b)
- Stop the iTerm TCC denial from being a silent skip loop (TRDD-VQ4LX7ND part 2)
- LOCAL design scope — the roots SSOT (3-pillars spec)
- Wire trdd-drift + trdd-reminder to BOTH design scopes (2/8 consumers)
- Wire trdd-state-reconciliation to BOTH design scopes (3/8 consumers)
- Wire the last 5 consumers to BOTH design scopes (8/8 — LOCAL scope complete)

### Performance

- Cut the machine-wide context floor 56% — move reference material off the prefix
- Stop consolidate re-spawning a 260k-token agent on an unchanged corpus
- Keep the LOCAL-scope rule under the context-floor ratchet, and cut 2.9 KB of boilerplate

### Tests

- S1c — fail the suite if any test writes the source tree (TRDD-RYZCVVKA)
- BLOCK any test writing outside its boundary (TRDD-RYZCVVKA, S1e)
- Extend the write sandbox into every CHILD process (S1g)

