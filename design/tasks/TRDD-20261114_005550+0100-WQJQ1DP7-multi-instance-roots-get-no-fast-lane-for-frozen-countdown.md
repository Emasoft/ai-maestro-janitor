---
trdd-id: WQJQ1DP7
title: Multi-instance roots get no fast lane for frozen countdown
column: todo
status: tasked
created: 2026-11-14T00:55:50+0100
updated: 2026-11-14T00:55:50+0100
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
approval-datetime: 2026-11-14T00:55:50+0100
parent-trdd: RJJGXPIK
derived: true
---

# Multi-instance roots get no fast lane for frozen countdown

## Why

RJJGXPIK follow-up. The fast lane requires a single-instance root. A root with several claude instances never gets the fast lane, so a frozen retry countdown there waits for the slow bar.

## Done when

A test with two claude instances on one project root and a frozen countdown in one of them asserts the frozen instance is diagnosed on the fast-lane bar (100 s), red on the current code.

## Approval log

- 2026-11-14T00:55:50+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
