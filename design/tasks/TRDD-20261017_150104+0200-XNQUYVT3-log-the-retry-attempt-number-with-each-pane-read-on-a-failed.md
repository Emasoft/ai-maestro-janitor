---
trdd-id: XNQUYVT3
title: Log the retry attempt number with each pane read on a failed unwedge step
column: todo
status: tasked
created: 2026-10-17T15:01:04+0200
updated: 2026-10-17T15:02:36+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-17T15:01:04+0200
---

# Log the retry attempt number with each pane read on a failed unwedge step

Derived from TRDD-315X5OWA (its FINDING lists rival causes H1 wall persists, H2 ESC not delivered or ignored; the final review added H3 ESC delivered, then something such as an idle-gated heartbeat resubmits into the same wall). The failed pane-policy line from 36287c9c logs reads= as bare classifications, which cannot separate them. Change: on a failed step, log each retry_wedge read with its parsed attempt number and the countdown text (e.g. reads=retry_wedge@4[2m50s],retry_wedge@1[5m0s]). Reading the result: an attempt number that DROPS, or a countdown that restarts near its maximum, means a new request was made (ESC delivered, then a resubmit: H3, or H1 via a resubmit). An UNCHANGED attempt across the step's reads (seconds apart, while real countdowns run minutes or hours) does NOT separate H1 (row stays after a cancelled request) from H2 (ESC ignored); only the 429 0s case advances fast enough to show the same request still retrying. VERIFIED: session_liveness._RETRY_WEDGE_RE captures the attempt number as group 1 (session_liveness.py:42) and pane_state.py imports it; reuse it, add no second parser. UNVERIFIED premise: Claude Code numbers retry attempts per request (fixtures show 1/300, 1/5, 5/300, consistent but not proof). Keep the ok line text unchanged (TRDD-UA4FAX67 greps it). Reaches daemon.log only after publish via scripts/publish.py and a local plugin update.

## Approval log

- 2026-10-17T15:01:04+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
