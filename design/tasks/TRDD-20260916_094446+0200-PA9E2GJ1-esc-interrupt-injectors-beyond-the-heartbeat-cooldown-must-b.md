---
trdd-id: PA9E2GJ1
title: Esc interrupt injectors beyond the heartbeat cooldown must be found and closed
column: todo
created: 2026-09-16T09:44:46+0200
updated: 2026-09-16T09:44:46+0200
current-owner: session
created-by: session
task-type: spike
min-approval-requirement: none
assignee: session
mandate: true
mandated-by: none
approved: true
approval-judge: session
approval-datetime: 2026-09-16T09:44:46+0200
parent-trdd: V3BQT7QE
derived: true
---

# Esc interrupt injectors beyond the heartbeat cooldown must be found and closed

Symptom: the owner reports Esc cannot stop the currently running agent turn. TRDD-6P0KUSO9 (landed, testing) already gated ONE candidate injector -- a cron heartbeat fire landing inside the E-1 interrupt cooldown now emits [janitor-quiet] and skips resume/chore tokens. The other three candidates named in the original report are still unverified: terminal-trigger osascript keystroke sends, a post-compact resume push, and the review-gate Stop hook demanding a fork.

Evidence: owner complaint 2026-09-15; TRDD-6P0KUSO9 (dispatch.py _phase_interrupt_cooldown, commit under TRDD-V3BQT7QE) already closes the heartbeat-fire candidate.

## Acceptance criteria
- [ ] Reproduce the stuck-Esc symptom with the janitor armed vs disarmed at least 3 times each, recording pass/fail counts, to localize whether a janitor-owned mechanism is the injector.
- [ ] For each of the 3 remaining candidates (terminal-trigger osascript keystroke, post-compact resume push, review-gate Stop hook fork), state PASS (does not re-inject within 5 min of an interrupt) or FAIL (does) with the exact log line or code path as evidence.
- [ ] Any candidate found to FAIL gets a fix landed making the 300s interrupt-cooldown (TRDD-6P0KUSO9 E-1 floor) apply to it too, verified by a test that simulates a user interrupt then asserts no re-injection for 300s.

## Approval log

- 2026-09-16T09:44:46+0200 — MANDATE issued by session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
