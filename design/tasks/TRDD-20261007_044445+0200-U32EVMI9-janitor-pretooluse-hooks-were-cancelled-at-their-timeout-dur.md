---
trdd-id: U32EVMI9
title: Janitor PreToolUse hooks were cancelled at their timeout during host stalls
column: testing
status: tasked
created: 2026-10-07T04:44:45+0200
updated: 2026-10-07T05:15:55+0200
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
- 2026-10-07T04:57:25+0200 — column → dev by main-agent@ai-maestro-janitor. first step merged; detector and lighter start-up path pending
- 2026-10-07T05:15:55+0200 — column → testing by main-agent@ai-maestro-janitor. merged on main; waits for a release

## STATE

2026-10-07: not started; held in the default column until the security agent's verdict exists. NEXT ACTION: record that verdict privately, then state the chosen response here in neutral terms.
The security agent's verdict on the harness behaviour is recorded in a private report. The chosen response is to give the guard hooks more time than the advisory hooks, to have the planned detector report every cancelled guard hook as a finding, and to track a lighter start-up path for the hooks on a separate card. The janitor's hooks stay best-effort by design; hard guarantees remain with the publish gate, the pre-push hook and the repository rulesets. Step one is merged on main (d28f3127, merge cd6f7119). Earlier count corrected: 87 cancellations of janitor pre-tool hooks across 22 tool calls, because subagent transcripts were not counted before.
2026-10-07: this card's own step (more time for guard hooks) is merged; the detector requirement is on TRDD-QX59MA4H and the start-up cost on TRDD-9XDND0BG.
