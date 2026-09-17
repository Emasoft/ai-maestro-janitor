---
trdd-id: OJK1MBU2
title: Observe whether the harness auto-compacts at turn end or only at the next prompt when the pane sits idle above its effective point
column: backburner
created: 2026-09-17T21:04:11+0200
updated: 2026-09-17T21:04:26+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: spike
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-17T21:04:11+0200
priority: medium
---

# Observe whether the harness auto-compacts at turn end or only at the next prompt when the pane sits idle above its effective point

## Approval log

- 2026-09-17T21:04:11+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Observe whether the harness auto-compacts at turn end or only at the next prompt when the pane sits idle above its effective point

The incident's single PreCompact timestamp (14:28:46, coinciding with a turn end that had a queued prompt) cannot separate the two models: (a) the harness compacts AT turn end once context is over its effective point, or (b) the harness only compacts when the NEXT prompt is submitted (turn end + queued prompt looks identical to a fresh prompt on an idle pane). Under model (b), the idle backstop's own /compact keystroke would itself be the trigger that starts a harness compaction first, then race its own queued /compact against it -- a double-compact by a different mechanism than guard 2 currently defends against. If (b) is confirmed, the backstop would need to send a non-/compact nudge (or nothing) instead of a real /compact keystroke while idle. Observation to make: put an idle pane above the effective compact point, autoCompactEnabled true, with NO prompt queued (disarm the heartbeat for the observation window so nothing submits one), and watch precompact-last-trigger.json for a PreCompact firing with no submitted prompt. Origin: TRDD-PH8SAQKS review 2 (coordinator, round 3).
