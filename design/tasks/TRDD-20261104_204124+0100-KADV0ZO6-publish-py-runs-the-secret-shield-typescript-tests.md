---
trdd-id: KADV0ZO6
title: publish.py runs the secret shield TypeScript tests
column: backburner
status: tasked
created: 2026-11-04T20:41:24+0100
updated: 2026-11-04T21:00:47+0100
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
- Every regex in hooks/secret-shield is timed with only TRDD-Q6LPJTPO's ratio rule (under 12 across an 8x size step, or under 2 ms at the larger size), without that card's load precondition or absolute limit, using a warm-up run and the median of at least 5 runs per size; this includes the 133a766a tests. One test covers every such regex without a hand list: the rules/ exports plus the module-private regexes in patterns.ts (TOKENS, URL_PASSWORD, the assignment and setting rules, MARK), exposed for the test or listed in one table that the test asserts complete. It times each on a failing tail at two sizes and, at the larger size, also runs it on the long failing prefix followed by a separator and a short, self-contained real match, asserting at least one hit, so a regex that silently gives up fails. The positive samples live in a table under tests/, built from split strings like the existing tests, never as literal tokens in rules/.
