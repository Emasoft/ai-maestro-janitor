---
trdd-id: BCZ1UCUT
title: Two tests point the memgrep crate at tools memgrep which does not exist
column: backburner
status: tasked
created: 2026-11-18T13:29:11+0100
updated: 2026-11-18T13:29:18+0100
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
approval-datetime: 2026-11-18T13:29:11+0100
---

# Two tests point the memgrep crate at tools memgrep which does not exist

- tools/memgrep path bug: tests/test_autorecall_hook.py:41 and tests/test_wikimem_fixture.py:35 set _MEMGREP_CRATE to tools/memgrep, which does not exist (the crate is scripts/memgrep), so the cargo build branch never runs and the tests skip where memgrep is not on PATH. Own card.

Found while working TRDD-SWQXCIOS.

## Approval log

- 2026-11-18T13:29:11+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Links

Parent context: TRDD-SWQXCIOS (bandit sweep).
