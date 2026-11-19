---
trdd-id: 7Q0I1HAC
title: HOOK-001 to HOOK-003 are catalogued with no kind so they can never become tickets
column: todo
status: tasked
created: 2026-11-19T13:07:49+0100
updated: 2026-11-19T13:07:54+0100
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
approval-datetime: 2026-11-19T13:07:49+0100
relevant-rules: [34]
---

# HOOK-001 to HOOK-003 are catalogued with no kind so they can never become tickets

## Symptom
design/specs/issue-codes.toml registers HOOK-001, HOOK-002, HOOK-003 without a `kind`; issue_catalog.ISSUE_CATALOG keeps only rows with a kind (scripts/lib/issue_catalog.py around lines 96-98), so raise_issue cannot route them, yet HOOK-002 and HOOK-003 appear in the findings ledger as MEDIUM. Under G34.1 every issue must become a ticket or a TRDD.

## Done means
- [ ] Each HOOK code has a kind (or a written reason it is exempt), the generated files are regenerated, and the drift test passes.

Filed under PRRD G34.1 (every issue becomes a ticket or a TRDD).

## Approval log

- 2026-11-19T13:07:49+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
