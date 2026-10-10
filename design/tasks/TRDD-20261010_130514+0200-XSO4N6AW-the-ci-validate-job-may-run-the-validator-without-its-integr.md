---
trdd-id: XSO4N6AW
title: The CI Validate job may run the validator without its integrity check ever verifying anything
column: verify_assumptions
status: tasked
created: 2026-10-10T13:05:14+0200
updated: 2026-10-10T13:05:14+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T13:05:14+0200
---

# The CI Validate job may run the validator without its integrity check ever verifying anything

## Approval log

- 2026-10-10T13:05:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Question

2026-10-10 13:05 Minted from TRDD-CWKM5218. Read from the validator's code (v5.16.2) and a local run, not observed in CI: under uvx the integrity check resolves no version, its fallback manifest URL returns 404, and with no cached manifest it returns True silently, so every janitor release's Validate job would have run a validator nobody verified. TO VERIFY FIRST: one CI run with a step that calls verify_self_integrity(fail_on_mismatch=False, quiet=False) from the same uvx build and prints the result, or read a CI log with the validator's own debug output. IF TRUE, decide: a CI step that fails when the check could not verify, or accept the skip until the upstream fix (Emasoft/claude-plugins-validation issue 243). No code before the verification.
