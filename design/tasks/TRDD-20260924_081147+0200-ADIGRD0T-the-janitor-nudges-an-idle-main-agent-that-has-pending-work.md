---
trdd-id: ADIGRD0T
title: The janitor nudges an idle main agent that has pending work
column: todo
created: 2026-09-24T08:11:47+0200
updated: 2026-10-10T04:58:02+0200
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
blocked-by: []
pre-block-column: 
blocker-probe: trddgrep --design-dir "$(git rev-parse --show-toplevel)/design" show 6ESS2MGE --porcelain | cut -f3
blocker-holds-if: not-match:^(complete|completed|cancelled|superseded|published|live|failed|live_auditing)$
status: tasked
---

# The janitor nudges an idle main agent that has pending work

owner directive of 2026-09-24 (verbatim in TRDD-WZKFSQ2N): "nudging the main agent when it is idle to resume working, telling him the pending TRDDs, the uncommitted work...". Today trdd-reminder fired 15 times this week and dirty-tree 29 times (ledger counts, 2026-09-17 to 2026-09-24), all into the ledger only (both are in dispatch.py's _ADVISORY_DETECTORS). Nothing types into an idle session that has pending work. Related: TRDD-I63GQJTK (in-flight workers look stalled), TRDD-L32WC0H7 (the liveness nudge). The routing decision (agent-facing resume prompt vs owner-facing heartbeat) is tracked on TRDD-6ESS2MGE only.

## Approval log

- 2026-09-24T08:11:47+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-10 04:58 UNBLOCKED (board drain). The routing decision this card waited on is recorded on TRDD-6ESS2MGE: under the owner's rule of 2026-09-27 a finding reaches the agent when the agent must act, and an idle agent with pending work is such a case, so the nudge is AGENT-FACING (a prompt into the idle session), not an owner-facing heartbeat line. Before building, compare with TRDD-HYTKG53C (a quiet heartbeat never re-engages a session that sits idle with pending work; in testing) and TRDD-C0RSMPRG (the resume injection was not done 107 times of 130): this card may already be covered by the first and depends on the second working.
- 2026-10-10T04:58:02+0200 — column → todo by main-agent@ai-maestro-janitor. the routing decision it waited on is recorded on 6ESS2MGE Cleared blocked-by (--clear-blocker override).
