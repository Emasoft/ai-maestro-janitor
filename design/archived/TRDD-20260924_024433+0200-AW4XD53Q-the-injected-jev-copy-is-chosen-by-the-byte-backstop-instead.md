---
trdd-id: AW4XD53Q
title: The injected Jev copy is chosen by the byte backstop instead of by priority within its byte budget
column: complete
created: 2026-09-24T02:44:33+0200
updated: 2026-09-24T08:29:47+0200
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

Found by the review of 862d30d4 (TRDD-RAEGS1D5). compose() admits items against the 8,000-token budget for both copies; the injected copy is then cut to the measured handoff room (about 5-6 KB) by the byte backstop, whose coarse stage order (pointers, non-owner down to a floor of 3, older owner messages, ...) decides the injected content on every normal run. Result on the three real transcripts: exactly 3 work items each, down from 4/6/4 before the backstop fired. Fix: run the same priority admission a second time for the injected render against its byte budget, so the backstop only fires on true overflow. Acceptance: at least the 4/6/4 non-owner items of aabd8b0c on the cached real scores, newest owner message present, nothing sliced; add a test with fewer than 3 non-owner items in total. A release blocker (review of e30b0885): 3/3/3 regresses the 4/6/4 this unreleased series already reached, on the owner's own complaint that the resumed session must learn what was done.

## Approval log

- 2026-09-24T02:44:33+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-24T02:45:28+0200 — column → todo by janitor-main-session. review of e30b0885: 3/3/3 regresses the 4/6/4 this unreleased series reached, on the owner's own complaint axis; it must not ship
- 2026-09-24T08:29:47+0200 — COMPLETE by janitor-main-session. acceptance met on cached real scores; trade accepted under delegation.

## Decision 2026-09-24 (delegated)

The owner-message trade is ACCEPTED (non-owner items first, per the owner's complaint that the resumed session must learn what was done). Acceptance is met on cached real scores: 5/6/5 non-owner items against a 4/6/4 target, newest owner message present, nothing sliced, and a test with fewer than 3 non-owner items is added. The measured cost (owner items inline 11/13/10 → 7/9/3; decision-passing owner items absent with no pointer 17/18/0 → 21/22/7) goes to the follow-up card below.

## Acceptance checklist

- [x] At least the 4/6/4 non-owner items of aabd8b0c on the cached real scores (measured: 5/6/5)
- [x] Newest owner message present, nothing sliced
- [x] Test added with fewer than 3 non-owner items in total
