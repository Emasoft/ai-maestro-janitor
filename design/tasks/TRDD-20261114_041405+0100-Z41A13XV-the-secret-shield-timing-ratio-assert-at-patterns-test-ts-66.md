---
trdd-id: Z41A13XV
title: The secret-shield timing-ratio assert at patterns.test.ts 661 fails under host load
column: todo
status: tasked
created: 2026-11-14T04:14:05+0100
updated: 2026-11-14T06:48:49+0100
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
- [ ] the assert passes 20 consecutive runs while the host is loaded to at least loadavg 45 (the one level observed on this host, not a design target) (e.g. a parallel full pytest run), measured and recorded
- [ ] a mutant that makes the guarded rule quadratic still fails it, measured and recorded

## Approval log

- 2026-11-14T04:14:05+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Notes

2026-11-14 main-agent ruling under TRDD-S6GX1DHN: TRDD-OD5Z90YL runs no further loaded timing campaign until the load target here is restated per core (the host has 14 cores) and an ambient-load bound is set. The Done-when's load of 45 or more is not to be used for a new campaign until then.
