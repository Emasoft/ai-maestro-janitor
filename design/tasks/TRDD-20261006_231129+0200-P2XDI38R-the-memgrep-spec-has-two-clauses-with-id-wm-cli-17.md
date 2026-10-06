---
trdd-id: P2XDI38R
title: The memgrep spec has two clauses with id WM-CLI-17
column: backburner
status: tasked
created: 2026-10-06T23:11:29+0200
updated: 2026-10-06T23:11:29+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T23:11:29+0200
---

# The memgrep spec has two clauses with id WM-CLI-17

Found during #322 (TRDD-8COB99QQ). In design/specs/wikimem-memgrep-spec.md two different clauses carry the id WM-CLI-17: one for trdd-backlink-is-optional-and-warned, one for update-mem-atom (the no-op refusal added by commit 349acb2d). A clause id must be unique. Fix: renumber one of them and update every citation (grep the repo for WM-CLI-17 in docs, skills, hook advice and tests).

## Approval log

- 2026-10-06T23:11:29+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
