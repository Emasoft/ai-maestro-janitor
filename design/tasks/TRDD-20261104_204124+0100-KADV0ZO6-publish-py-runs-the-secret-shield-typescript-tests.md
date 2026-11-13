---
trdd-id: KADV0ZO6
title: publish.py runs the secret shield TypeScript tests
column: backburner
status: tasked
created: 2026-11-04T20:41:24+0100
updated: 2026-11-13T17:39:15+0100
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
approval-datetime: 2026-11-04T20:41:24+0100
npt: []
eht: [OD5Z90YL]
---

# publish.py runs the secret shield TypeScript tests

The secret shield's TypeScript tests (hooks/secret-shield/tests) run in no automated gate; TRDD-TEP6F3A3 records this as a prerequisite of wiring the mod, and this card blocks the wiring card TRDD-2V7OAUPE. Where the gate runs and how is decided under Decision 2026-11-04 below. Found during TRDD-TEP6F3A3.

## Approval log

- 2026-11-04T20:41:24+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Decision 2026-11-04

- 2026-11-04 main-agent: the gate is a publish.py stage that runs before stage_bump, like the other pre-bump checks, and fails closed when the claude CLI is missing or cannot run the tests, as pyright does here. A CI job may be added beside it, never instead of it: CI runs after publish.py has pushed the tag, so it cannot block the publish. Before writing the stage, record the exact claude plugin test invocation the workers ran on the shield. That claude plugin test runs the tests in Claude Code's bundled runtime is inferred from its passing on (?i:...) groups and lookbehinds; the bundled Bun cannot be invoked directly to confirm it. Before the gate goes live, the shield's timing tests with absolute limits (for example under 1 s) become growth-ratio checks, because this host's load has stayed above its core count (TRDD-Q6LPJTPO), so an absolute limit in a blocking gate would flake.

## Done when

- The exact claude plugin test invocation that runs hooks/secret-shield/tests is recorded on this card.
- A publish.py stage before stage_bump runs that invocation and exits non-zero, blocking the publish, both when a shield test fails and when the claude CLI is missing or cannot run; each case is shown by a real run, including one where publish.py itself runs inside a Claude Code session.
- The publish stage runs the ReDoS harness of TRDD-OD5Z90YL over every regex in hooks/secret-shield, and that card's Done-when is met.
- [ ] the publish gate stage also runs hooks/liveness/tests/liveness.test.ts (scope change 2026-11-13)

## Scope change 2026-11-13

2026-11-13: scope widened - hooks/liveness/tests/liveness.test.ts (TRDD-R9NLNV3W, commit 3a73c1b9) is a second TypeScript test suite that no CI or publish gate runs; the gate stage added here must run both.
