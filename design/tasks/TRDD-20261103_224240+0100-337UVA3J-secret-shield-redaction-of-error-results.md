---
trdd-id: 337UVA3J
title: Secret-shield redaction of error results
column: design
status: tasked
created: 2026-11-03T22:42:40+0100
updated: 2026-11-03T22:46:29+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-03T22:42:40+0100
---

# Secret-shield redaction of error results

## Problem
register.ts skips tool results marked as errors, so a secret printed in an error message reaches Claude unredacted.
## Decide
Redact error text the same way, or leave it. Cost of redacting: a person debugging the failure no longer sees the failing token. Measure first what an error result looks like to the mod (text field, shape) for Bash and for an MCP tool.
Start at register.ts:85, where error results are skipped. This card does not block wiring.
## Done when
A test shows a secret in an error result is hidden (or the decision to leave it is recorded with its reason), and nothing else in error output changes.
Found during TRDD-M1218EMH.

## Approval log

- 2026-11-03T22:42:40+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
