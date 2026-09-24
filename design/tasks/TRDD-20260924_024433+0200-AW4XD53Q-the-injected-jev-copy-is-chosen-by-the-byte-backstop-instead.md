---
trdd-id: AW4XD53Q
title: The injected Jev copy is chosen by the byte backstop instead of by priority within its byte budget
column: todo
created: 2026-09-24T02:44:33+0200
updated: 2026-09-24T02:45:28+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T02:44:33+0200
---

# The injected Jev copy is chosen by the byte backstop instead of by priority within its byte budget

Found by the review of 862d30d4 (TRDD-RAEGS1D5). compose() admits items against the 8,000-token budget for both copies; the injected copy is then cut to the measured handoff room (about 5-6 KB) by the byte backstop, whose coarse stage order (pointers, non-owner down to a floor of 3, older owner messages, ...) decides the injected content on every normal run. Result on the three real transcripts: exactly 3 work items each, down from 4/6/4 before the backstop fired. Fix: run the same priority admission a second time for the injected render against its byte budget, so the backstop only fires on true overflow. Acceptance: at least the 4/6/4 non-owner items of aabd8b0c on the cached real scores, newest owner message present, nothing sliced; add a test with fewer than 3 non-owner items in total. Not a release blocker: the RAEGS1D5 publish criteria are met at 3/3/3.

## Approval log

- 2026-09-24T02:44:33+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-24T02:45:28+0200 — column → todo by janitor-main-session. review of e30b0885: 3/3/3 regresses the 4/6/4 this unreleased series reached, on the owner's own complaint axis; it must not ship
