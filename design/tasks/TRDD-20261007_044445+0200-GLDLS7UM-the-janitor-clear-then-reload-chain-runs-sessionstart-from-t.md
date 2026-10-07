---
trdd-id: GLDLS7UM
title: The janitor clear-then-reload chain runs SessionStart from the old plugin version
column: todo
status: tasked
created: 2026-10-07T04:44:45+0200
updated: 2026-10-07T04:44:54+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T04:44:45+0200
---

# The janitor clear-then-reload chain runs SessionStart from the old plugin version

## Problem
The janitor's reload chain types the clear first and the plugin reload after, so the SessionStart that injects the handoff runs the hooks of the version the process started on.

## Evidence
18 SessionStart log entries since 2026-10-05 name root 3.7.0, the newest at 03:52:24 on 2026-10-07, 4 seconds before the reload. Sessions that only cleared kept 3.7.0 across releases 3.7.3 to 3.8.2.

## Consequence
Fixes that live in SessionStart hooks or their timeouts (cards KVUVV9D2, 9438CGJZ, C7M4RXQ2, D7RLXAN1) cannot be observed in a long-lived session, and the handoff injection of 2026-10-07 ran as 3.7.0.

## Not established
Whether a reload alone moves the hook root (the next clear decides), and whether the logged root is the one the harness ran the hook from.

## Scope
The general rule that a running session keeps old plugin code is already on the memory page claude-code-plugin-rollout-staleness. This card is only about the ORDER inside the janitor's own chain.

## Options (none chosen)
Reload before the clear; or a second SessionStart-equivalent step after the reload.

## Acceptance
- [ ] After one janitor-driven reload, the SessionStart log entry of the resumed session names the newest cached version.

## Approval log

- 2026-10-07T04:44:45+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

2026-10-07: not started. NEXT ACTION: read the SessionStart log entry after the next clear-then-reload of a janitor-armed session; if it names 3.7.0, reorder the chain per the options above.
