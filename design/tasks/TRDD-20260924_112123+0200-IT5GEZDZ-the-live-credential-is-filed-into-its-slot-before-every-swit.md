---
trdd-id: IT5GEZDZ
title: The live credential is filed into its slot before every switch away from it
column: testing
created: 2026-09-24T11:21:23+0200
updated: 2026-09-27T16:11:04+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T11:21:23+0200
status: tasked
---

# The live credential is filed into its slot before every switch away from it

Release 1 of TRDD-RAEGS1D5; mirror rules on TRDD-4XND73XD. Depends on the daemon's primary read (C6). At a switch: read live, file it into the OUTGOING account's slot (only when the fingerprint differs and expiresAt is newer), then write the new live. Only while the janitor owns oauth-rotator-tick (not yielded to the ai-maestro server). This is what keeps a switched-away account's slot alive (TRDD-K0PMVRN6 hypothesis H1). Acceptance: a test that fails without it; one real switch in which the outgoing slot's fingerprint equals the live credential's at switch time.

## Approval log

- 2026-09-24T11:21:23+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-27T16:11:04+0200 — column → testing by user. owner batch acceptance 2026-09-27 ('complete all TRDDs'); mirror landed e00e2c7c re-verified by main; live-switch observation remains as testing evidence

## Review corrections 2026-09-24

Handback condition: before the ai-maestro server's oauth-rotator-tick flag returns, the server must implement the same at-switch mirror (record it on TRDD-4XND73XD), or the slots decay again after the handback.

## Acceptance

- [x] at a switch, the pre-switch live credential is filed into the OUTGOING account slot in _switch_blob, before the new live write
- [x] guards: janitor-owns-tick only (claimed_chores, fail-toward-coverage), fp-differs, expiresAt-newer — never regress a slot
- [x] best-effort: a failed slot write logs and the switch proceeds; never blocks or fails the switch
- [x] 4 new tests incl. the failing-without-it acceptance test
- [x] live one-real-switch observation (outgoing slot fp == live fp at switch time) — runtime evidence remaining in testing
