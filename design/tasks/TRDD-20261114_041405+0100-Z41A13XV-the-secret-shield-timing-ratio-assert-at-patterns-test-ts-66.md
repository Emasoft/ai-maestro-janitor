---
trdd-id: Z41A13XV
title: The secret-shield timing-ratio assert at patterns.test.ts 661 fails under host load
column: todo
status: tasked
created: 2026-11-14T04:14:05+0100
updated: 2026-11-14T08:22:06+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-14T04:14:05+0100
parent-trdd: 3GP0D06D
derived: true
---

# The secret-shield timing-ratio assert at patterns.test.ts 661 fails under host load

## Problem
Observed once at loadavg ~45 inside pytest: patterns.test.ts:661 failed on its linear(small.ms, big.ms) ratio assert (line 664); three reruns passed. The test now gates every publish through scripts/run_secret_shield_tests.py (step 2b in stage_tests, G3b in run_gate), so a timing flake on a loaded host blocks a release. Evidence: TRDD-3GP0D06D notes.

## Do
Make the assert load-robust (for example a median of N runs, or an absolute ceiling with margin) without weakening what it detects. Related: TRDD-MEYVDFJ9.

## Done when
- [ ] the ratio assert at hooks/secret-shield/tests/patterns.test.ts:657 and :664, or the check that replaces it in TRDD-OD5Z90YL increment 1b (whichever is in the module when this is measured; that one closes this card), passes 20 consecutive probes of the real secret-shield module while 35 CPU-only workers (2.5 per core on the dev host) run for the whole campaign under the TRDD-OD5Z90YL D8 harness, measured and recorded; contention, not load level, is what the timing check must survive, so this replaces the earlier criterion of load 45 or more, the one level at which it was seen to fail (main-agent ruling under TRDD-S6GX1DHN, 2026-11-14)
- [ ] a mutant that makes the guarded rule quadratic still fails it, measured and recorded

## Approval log

- 2026-11-14T04:14:05+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Notes

2026-11-14 main-agent ruling under TRDD-S6GX1DHN: TRDD-OD5Z90YL runs no further loaded timing campaign until the load target here is restated per core (the host has 14 cores) and an ambient-load bound is set. The Done-when's load of 45 or more is not to be used for a new campaign until then.
2026-11-14: the D8 harness (tests/harness/redos_load_harness.py, a2d0d5d8) matches the two tests by exact describe and test name (Z41_TESTS). If increment 1b replaces or renames them, the harness reports Z41A13XV incomplete, never pass, until Z41_TESTS is edited to the new names.
