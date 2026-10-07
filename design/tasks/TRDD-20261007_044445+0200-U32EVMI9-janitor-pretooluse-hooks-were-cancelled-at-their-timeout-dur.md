---
trdd-id: U32EVMI9
title: Janitor PreToolUse hooks were cancelled at their timeout during host stalls
column: backburner
status: tasked
created: 2026-10-07T04:44:45+0200
updated: 2026-10-07T04:44:55+0200
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

# Janitor PreToolUse hooks were cancelled at their timeout during host stalls

## Facts
52 PreToolUse hook cancellations with timedOut true were recorded in this project's session transcripts between 2026-10-05 and 2026-10-06, across seven janitor hooks, in bursts that coincide with host stalls. None since the evening of 2026-10-06, which shows only that no comparable stall recurred. Durations sat close to the limits, so ordinary slowness is not ruled out.

## Not established
What the harness does with a tool call whose hook was cancelled. That question is assigned to the security agent and its findings are kept in a private report.

## Related
TRDD-QX59MA4H (the detector half), TRDD-9438CGJZ.

## Acceptance
- [ ] The security agent's verdict is recorded (privately) and this card states the chosen response in neutral terms.

## Approval log

- 2026-10-07T04:44:45+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

2026-10-07: not started; held in the default column until the security agent's verdict exists. NEXT ACTION: record that verdict privately, then state the chosen response here in neutral terms.
