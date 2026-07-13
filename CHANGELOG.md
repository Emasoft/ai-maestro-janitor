# Changelog

All notable changes to this project will be documented in this file.

## [0.42.0] - 2026-07-13

### Bug Fixes

- Restore the missing exec bit on the detector
- Mask git remote credentials in the report (TRDD-ULYUOP0Y)
- Stop misclassifying local FUSE mounts as network (TRDD-ULYUOP0Y)
- Lock the plugin-update-requests RMW against lost updates (TRDD-YMTUPQER)
- Git -c arg-skip in verb parse; drop unreachable python-deny branch (TRDD-DQJVVMFN)
- Launchd witness compares labels, not volatile PID column (TRDD-DQJVVMFN)
- Plugin description claimed a 'durable' cron and 'No external daemons' — both false
- A lesson had no keywords, so it was unreachable — give it its address back
- Four guards that did not guard (audit findings #1/#4/#5/#6)
- CRITICAL — a crash-recovery could DELETE a page and lose it forever (F1)
- The conflict pass could never commit, and harvest never converged (F2)
- A "new page" write could silently overwrite an existing memory (F3)
- The audit chain broke ITSELF, then cried tampering forever (F4)
- A captured account could be silently orphaned by the daemon tick
- Racing key-minters orphaned a key, breaking chain verification (F6, F7)
- The USER-memory backup mirrored a live transaction, and an index could block restore (F10)
- The recovery audit log destroyed its own tamper-evidence, then buried itself in noise (F8, F9)
- "staged file is gone" is not proof a write applied (F5)
- A lesson could be silently truncated, and the crash journal was not durable (F11, F12)
- Harden the iTerm AppleScript sink; share the robust update matcher (findings 3, 4)
- Stop writing the OAuth authorization code to disk and to the log (finding 2)
- 20 lessons were silently missing from the index (two bugs, both mine)
- Our own context guard was the machine's #1 prompt-cache breaker (TRDD-K1RJUYGK)
- The injection guard was still injecting on its own hot path (TRDD-K1RJUYGK)
- Collapse the nested if in raw_footnote_defs (clippy 1.97 -D warnings)
- Clear CPV strict-validate gate — 1 CRITICAL + 3 real findings (not scanner appeasement)

### Documentation

- Add Y9KM5RCJ — release-triggered janitor self-update
- Y9KM5RCJ complete — record impl commit 5554a51 + test pass
- Add YMTUPQER — universal per-heartbeat plugin auto-update
- YMTUPQER complete — impl 92bb9af + tests 38cb35d, suite pass
- Add janitor beat-tasks + limitations wikimem (PROJECT scope)
- Refresh CLAUDE.md project map for YMTUPQER symbols
- Record the DEAD SECURITY SESSION gotcha + its lesson (2026-07-12)
- Stay on topic — a case page holds case facts, methodology lives in one page
- Add TRDD-DQJVVMFN — test process sandbox (complete)
- Add TRDD-ULYUOP0Y — environment detection expansion (complete)
- TRDD-ULYUOP0Y wave-2 addendum + implementation-commits
- Capture the identify-environment prober design + the "anchor a subprocess loses" lesson
- TRDD-ULYUOP0Y wave-3 addendum + implementation-commits (gh/CI/releases/registries/homebrew/fork/topology)
- Refresh CLAUDE.md project map after the code-review source edits
- The heartbeat cron is session-scoped BY DESIGN — 'durable' was never a real param
- The heartbeat cron is session-scoped by design — retract the 'durable downgrade' claim
- A lesson is a guardrail, not a story — prescribe the terse form
- YRPUSIFY's bucketing approach is falsified — the strip, not the text, breaks the cache
- Refresh the CLAUDE.md project map after the cache-thrash fix
- Add TRDD-9K0O5YBQ (Claude Code compat audit) + TRDD-SLFMG704 (cross-plugin handoff)
- SLFMG704 — hook: Stop belongs to NO plugin; and three ai-maestro Stop hooks are broken
- SLFMG704 — reconcile the offender table with the completed attribution
- SLFMG704 — prove AgentLens's "hook: <Event>" label is a boundary, not an emitter
- K1RJUYGK — RETRACT the attribution; the fix stands, the blame does not
- Retitle K1RJUYGK — a retraction that leaves the headline standing is not a retraction
- SLFMG704 — RETRACT the "broken ai-maestro hooks" finding; it was my query that was broken
- SLFMG704 — PostToolBatch has no owner; the boundary-not-emitter proof gets its cleanest leg
- Split the two oversized memory SKILL.md bodies under the CPV token gate (lossless)

### Features

- Release-triggered janitor self-update (TRDD-Y9KM5RCJ)
- Universal user-scope auto-update via daemon signal (TRDD-YMTUPQER)
- Detect a security session that cannot reach the keychain
- Full secret-safe environment prober (TRDD-ULYUOP0Y)
- Add Claude auth-mode / subscription detection (TRDD-ULYUOP0Y)
- Git/GitHub/wikimem/plugins detection + JSON-to-disk (TRDD-ULYUOP0Y)
- Count standalone (non-plugin) skills (TRDD-ULYUOP0Y)
- Gh user, CI actions/Claude-action, releases, registries, homebrew-tap-trust, fork, topology (TRDD-ULYUOP0Y)
- A lesson is an ATOM — give it id, status, key-phrases (schema v4)

### Miscellaneous

- Bootstrap .trashcan (gitignore + survival markers) after first safe-delete

### Performance

- 14 memory-frequency knobs -> 1 command (-1262 tok EVERY session)

### Tests

- Real no-mock tests for universal user-scope auto-update (TRDD-YMTUPQER)
- Add audit mode — record every process spawn (Phase 0)
- Deny-by-default process + signal guard (S1h)
- Prove the process guard guards (35 tests + falsification)
- Witness the two states that are not files (S1i)

