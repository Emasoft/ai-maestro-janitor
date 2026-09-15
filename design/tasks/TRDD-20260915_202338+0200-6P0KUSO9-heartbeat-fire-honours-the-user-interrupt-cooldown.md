---
trdd-id: 6P0KUSO9
title: Heartbeat fire honours the user-interrupt cooldown
column: todo
created: 2026-09-15T20:23:38+0200
updated: 2026-09-15T20:23:42+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: bugfix
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-15T20:23:38+0200
parent-trdd: V3BQT7QE
priority: high
---

# Heartbeat fire honours the user-interrupt cooldown

## Symptom
Owner: Esc cannot stop the agent. A cron heartbeat fire lands as a fresh turn seconds after an Esc with no interrupt-aware defer, and its [janitor-resume]/chore tokens restart work.

## Evidence
scripts/dispatch.py has no cooldown check against a recent user interrupt before acting on a heartbeat fire.

## Acceptance
- [ ] dispatch.py: if `user_intent.recently_interrupted(...)` (E-1) is within the cooldown (default 300s), the fire emits only `[janitor-quiet]` and one log line `heartbeat: quiet, user interrupted <age>s ago`; no resume, no chore, no keep-going token
- [ ] tests with a real transcript fixture

## Files
scripts/dispatch.py, tests/test_dispatch_phases.py

## Approval log

- 2026-09-15T20:23:38+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
