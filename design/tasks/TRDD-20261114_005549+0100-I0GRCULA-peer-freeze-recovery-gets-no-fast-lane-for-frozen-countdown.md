---
trdd-id: I0GRCULA
title: peer-freeze-recovery gets no fast lane for frozen countdown
column: todo
status: tasked
created: 2026-11-14T00:55:49+0100
updated: 2026-11-14T00:58:20+0100
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
approval-datetime: 2026-11-14T00:55:49+0100
parent-trdd: RJJGXPIK
derived: false
---

# peer-freeze-recovery gets no fast lane for frozen countdown

## Why

RJJGXPIK follow-up. peer-freeze-recovery gathers with fast_lane=False (diagnose_root is called with fast_lane False there), so a frozen retry countdown seen through that path waits for the slow bar. The fast lane therefore never runs while the daemon is dark.

## Done when

A test drives a frozen countdown through peer-freeze-recovery and asserts it is diagnosed on the fast-lane bar (100 s), red on the current code.
First: the owner decides whether peer-freeze-recovery should get the fast lane at all (open question to the owner, 2026-11-14). The test above applies only if the answer is yes; a no closes this card (cancelled).

## Approval log

- 2026-11-14T00:55:49+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
