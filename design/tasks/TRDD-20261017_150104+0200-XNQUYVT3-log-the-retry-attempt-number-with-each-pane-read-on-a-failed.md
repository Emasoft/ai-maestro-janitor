---
trdd-id: XNQUYVT3
title: Log the retry attempt number with each pane read on a failed unwedge step
column: todo
status: tasked
created: 2026-10-17T15:01:04+0200
updated: 2026-10-17T15:01:04+0200
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

Derived from TRDD-315X5OWA (its FINDING lists rival causes H1 wall persists, H2 ESC not delivered or ignored, and H3 ESC delivered then something such as an idle-gated heartbeat resubmits into the same wall). The failed pane-policy line from 36287c9c logs reads= as bare classifications, which cannot separate them. Change: on a failed step, log each retry_wedge read with its parsed attempt number (e.g. reads=retry_wedge@4,retry_wedge@1). A counter that resets to 1 after the ESC means a new request was sent (delivered, then resubmitted: H3, or H1 via a resubmit); a counter that keeps advancing means the same request kept retrying (H2). The attempt parse already exists for the retry_wedged diagnosis (session_liveness _RETRY_WEDGE_RE); reuse it, add no second parser. Keep the ok line text unchanged (TRDD-UA4FAX67 greps it). Reaches daemon.log only after publish via scripts/publish.py and a local plugin update.

## Approval log

- 2026-10-17T15:01:04+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
