---
trdd-id: ZKXQXHBI
title: The janitor daemon reads the live credential's primary item behind its own latch
column: todo
created: 2026-09-24T11:21:18+0200
updated: 2026-09-24T11:21:18+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T11:21:18+0200
---

# The janitor daemon reads the live credential's primary item behind its own latch

Release 1 of TRDD-RAEGS1D5; design on TRDD-4XND73XD (decision 2 of TRDD-WZKFSQ2N, term M9). Today the daemon skips the primary read by policy (JANITOR_ROTATOR_HEADLESS) and works from the -livebak mirror, which is why the live account's slot twin goes stale (TRDD-K0PMVRN6). Change: one bounded read per tick; a separate primary-read latch (a denial trips it at once, timeouts need 3 in a row, cooldown 600 s); a refusal falls back to the mirror WITHOUT tripping the shared keychain latch (errSecInteractionNotAllowed -25308), logs once per state change, and never retries within the tick. Prerequisite: test the read from the daemon's LaunchAgent context first (the 2026-09-24 test ran from an interactive session). Acceptance: a test per latch rule that fails without the change; one real daemon tick logs a primary read.

## Approval log

- 2026-09-24T11:21:18+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
