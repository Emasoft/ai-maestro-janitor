---
trdd-id: T36Z4ACR
title: A publish gate runs the secret-shield TS suite
column: todo
status: tasked
created: 2026-11-05T02:01:56+0100
updated: 2026-11-05T02:01:56+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-05T02:01:56+0100
---

# A publish gate runs the secret-shield TS suite

## Problem
No automated gate runs the secret-shield TypeScript suite. scripts/publish.py stage_tests (publish.py:1829-1871) runs pytest only; no .github workflow calls claude plugin test; no pytest test runs it (tests/test_publish_lock_guard.py:211 only mentions plugin test code in a docstring); and nothing type-checks hooks/ (carried from earlier reports, not re-measured). Every shield family so far (d711e5f8, dbd5aaf9, 28b42512) was proven only by hand in a scratch plugin shell.

## Done when
 - [ ] The publish test stage fails when the secret-shield TS suite fails.
 - [ ] A pytest test or a publish stage builds a faithful shell: the real .claude-plugin/plugin.json, hooks/secret-shield/ copied, and a hooks.json listing ./secret-shield/register.ts until TRDD-2V7OAUPE wires the module.
 - [ ] It runs claude plugin test and requires exit 0 with 0 fail; a missing claude CLI fails the stage instead of skipping it.
 - [ ] CI parity is decided and written down: CI runs the suite, or this card states why it does not.
 - [ ] Proof: one deliberately failing TS test blocks a publish.py dry run.

## Related
TRDD-2V7OAUPE (wiring the shield), TRDD-Q6LPJTPO (the token families), TRDD-6FB7PKU2 (interim hand-run box).

## Approval log

- 2026-11-05T02:01:56+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
