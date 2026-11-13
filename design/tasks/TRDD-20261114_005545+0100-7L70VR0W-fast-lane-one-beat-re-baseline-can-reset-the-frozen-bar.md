---
trdd-id: 7L70VR0W
title: Fast lane one-beat re-baseline can reset the frozen bar
column: todo
status: tasked
created: 2026-11-14T00:55:45+0100
updated: 2026-11-14T00:56:47+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-14T00:55:45+0100
parent-trdd: RJJGXPIK
derived: true
---

# Fast lane one-beat re-baseline can reset the frozen bar

## Why

RJJGXPIK follow-up. The fast-lane beat's own re-baseline may reuse a stale baseline for one beat (not shown). If so, a single beat that re-baselines the episode may reset the 100 s frozen bar, so the fast lane may wait longer than intended before a frozen countdown is acted on. This is the hazard named in the RJJGXPIK STATE; its exact trigger is to be confirmed by a test.

## Approval log

- 2026-11-14T00:55:45+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Done when

A test seeds a frozen countdown episode, runs a beat that re-baselines, and asserts the 100 s frozen bar is not reset (red on the current code if the hazard is real, or a recorded measurement that it is not).
