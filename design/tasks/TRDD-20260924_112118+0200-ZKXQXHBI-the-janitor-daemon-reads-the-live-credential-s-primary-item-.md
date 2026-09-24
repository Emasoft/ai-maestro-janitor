---
trdd-id: ZKXQXHBI
title: The janitor daemon reads the live credential's primary item behind its own latch
column: todo
created: 2026-09-24T11:21:18+0200
updated: 2026-09-24T11:29:16+0200
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

Release 1 of TRDD-RAEGS1D5; design on TRDD-4XND73XD (decision 2 of TRDD-WZKFSQ2N, term M9). Today the daemon skips the primary read by policy (JANITOR_ROTATOR_HEADLESS) and works from the -livebak mirror, the leading, unverified hypothesis (H1 on TRDD-K0PMVRN6) for why the live account's slot twin goes stale. Change: one bounded read per tick; a separate primary-read latch (a denial trips it at once, timeouts need 3 in a row, cooldown 600 s); a refusal falls back to the mirror WITHOUT tripping the shared keychain latch (errSecInteractionNotAllowed -25308), logs once per state change, and never retries within the tick. Prerequisite: test the read from the daemon's LaunchAgent context first (the 2026-09-24 test ran from an interactive session). Acceptance: a test per latch rule that fails without the change; one real daemon tick logs a primary read.

## Approval log

- 2026-09-24T11:21:18+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Review corrections 2026-09-24

The prerequisite read test must itself be safe: one bounded read with a timeout and no prompt allowed (may_prompt=False), outside the shared keychain-latch path, from the daemon's own context. A careless test can raise a dialog or trip the machine-wide denied latch, which stops rotation.
Logging that becomes live once the daemon reads the primary: (1) the F1 "primary live credential UNREADABLE" line must say whether the read was skipped by policy or refused; (2) since e322d8e1, cmd_capture's unresolved-account branch and the F5 UNRESOLVABLE line in _reconcile_live_email can both fire every tick during a /roles outage: make both durable rotator.log lines, deduplicated per fingerprint. Two /roles calls per tick (capture plus reconcile) during such an outage are the accepted cost.
