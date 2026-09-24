---
trdd-id: TK529Q0F
title: The rotator's inability to rotate reaches the agent or the owner at once
column: todo
created: 2026-09-24T11:21:24+0200
updated: 2026-09-24T11:29:24+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T11:21:24+0200
---

# The rotator's inability to rotate reaches the agent or the owner at once

Release 1 of TRDD-RAEGS1D5. On 2026-09-24 the rotator logged "no usable slot twin" and credential-dead refreshes for hours, and the `oauth-login-needed` line reached the owner only after the owner had rotated by hand (TRDD-K0PMVRN6). Change: when a tick cannot rotate (no usable twin, every alternate dead or near its limit) the condition is raised immediately to the owner-facing heartbeat, deduplicated per state change, not only to the ledger. Routing follows TRDD-6ESS2MGE. Acceptance: a test that fails without it.

## Approval log

- 2026-09-24T11:21:24+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Review corrections 2026-09-24

Routing: this goes to the OWNER-facing heartbeat, an explicit exception to decision 3 on TRDD-WZKFSQ2N (findings go to the agent): a can't-rotate state needs a human re-login, which only the owner can do.
