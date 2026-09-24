---
trdd-id: 6ESS2MGE
title: Advisory findings reach the agent or the owner instead of dying in the ledger
column: design
created: 2026-09-24T08:11:58+0200
updated: 2026-09-24T08:11:58+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T08:11:58+0200
---

# Advisory findings reach the agent or the owner instead of dying in the ledger

dispatch.py's _ADVISORY_DETECTORS (trdd-reminder, dirty-tree, gitignore-coverage, github-issues-watch, gh-reply-watch, and others) are quiet-filtered to the findings ledger, so new GitHub issues #306 and #307 (2026-09-22/23), 29 dirty-tree hits and 15 trdd-reminder hits in one week (ledger counts, 2026-09-17 to 2026-09-24) never reached anyone. The 2026-08-12 owner rule ("a fire prints janitor heartbeat, and ONLY adds to it when something genuinely needs the human") and the 2026-09-24 directive (TRDD-WZKFSQ2N) now conflict. OWNER DECISION needed on routing. TRDD-ADIGRD0T is the agent-facing half.

## Approval log

- 2026-09-24T08:11:58+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
