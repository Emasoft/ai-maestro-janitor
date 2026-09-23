---
trdd-id: 98SP58TJ
title: The Jev decision question passes nearly every owner message, so decision priority means owner priority
column: backburner
created: 2026-09-23T23:59:11+0200
updated: 2026-09-23T23:59:11+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-23T23:59:11+0200
---

# The Jev decision question passes nearly every owner message, so decision priority means owner priority

Measured 2026-09-23: DECISION_QUESTION (it includes 'an instruction the user stated') passed 28 of 38 owner items on the 49 MB transcript and 250 on the 258 MB one (total owner items there not counted). decision_passed then gives owner messages first claim on the guaranteed slot and on every pointer slot, ahead of relevant tool results. Measure the question on real owner messages (continue, status questions, directives) and tighten the question or its threshold so routine prompts do not pass. Not a release blocker: the owner ruled only that the NEWEST owner message comes first (fe38e095); this card sharpens it. Found by the review of 23713d53 (TRDD-RAEGS1D5).

## Approval log

- 2026-09-23T23:59:11+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
