---
trdd-id: ADIGRD0T
title: The janitor nudges an idle main agent that has pending work
column: todo
created: 2026-09-24T08:11:47+0200
updated: 2026-09-24T08:11:47+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T08:11:47+0200
---

# The janitor nudges an idle main agent that has pending work

owner directive of 2026-09-24 (verbatim in TRDD-WZKFSQ2N): "nudging the main agent when it is idle to resume working, telling him the pending TRDDs, the uncommitted work...". Today trdd-reminder fired 15 times this week and dirty-tree 29 times, all into the ledger only (both are in dispatch.py's _ADVISORY_DETECTORS). Nothing types into an idle session that has pending work. Related: TRDD-I63GQJTK (in-flight workers look stalled), TRDD-L32WC0H7 (the liveness nudge). Open owner decision: route these findings to the AGENT (a resume prompt typed when idle) while the owner-facing heartbeat stays quiet. That reconciles with the 2026-08-12 quiet-heartbeat rule.

## Approval log

- 2026-09-24T08:11:47+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
