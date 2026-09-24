---
trdd-id: DZ1KOGAC
title: Control inputs fill the owner tier of the injected Jev copy
column: todo
created: 2026-09-24T11:21:11+0200
updated: 2026-09-24T11:21:11+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T11:21:11+0200
---

# Control inputs fill the owner tier of the injected Jev copy

Same run (E2). The owner tier of the injected copy is filled with control inputs: `resume`, `RESUME`, `/compact` twice, `/goal` and `/eli5` command wrappers. They displace the owner's real instructions. Whether they were decision-passing is not yet measured. Proposed direction (pending the advisor): slash-command records and bare control words are excluded from the injected owner tier and are still pointed at. Acceptance: on the three transcripts no injected owner item is a bare control word or an argument-less slash command; a test fails without the fix. Release blocker for TRDD-RAEGS1D5.

## Approval log

- 2026-09-24T11:21:11+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
