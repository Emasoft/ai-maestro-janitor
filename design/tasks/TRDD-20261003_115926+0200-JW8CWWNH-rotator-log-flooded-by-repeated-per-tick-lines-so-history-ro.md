---
trdd-id: JW8CWWNH
title: Rotator log flooded by repeated per-tick lines so history rotates away in hours
column: backburner
status: tasked
created: 2026-10-03T11:59:26+0200
updated: 2026-10-03T11:59:26+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: user
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T11:59:26+0200
parent-trdd: JSQSJ3PZ
---

# Rotator log flooded by repeated per-tick lines so history rotates away in hours

rotator.log (262 KB rotation) holds only about 3 h because the same unreadable/primary/keepalive lines repeat every tick (372 repeats measured 2026-10-03). The rotation destroyed the history needed to date a spare first failure (R8).

Proposed: log a repeated line once and then a count on change, and keep a compact per-slot event history (last 10: time, outcome class, http status) in state.json.

Related: TRDD-B78NJU35, TRDD-HSRERK5S.

## Approval log

- 2026-10-03T11:59:26+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
