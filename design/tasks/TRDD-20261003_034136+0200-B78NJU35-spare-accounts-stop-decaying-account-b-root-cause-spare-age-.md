---
trdd-id: B78NJU35
title: Spare accounts stop decaying (account B root cause, spare-age alert)
column: testing
status: tasked
created: 2026-10-03T03:41:36+0200
updated: 2026-10-03T11:59:36+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:41:36+0200
project-id: ai-maestro-janitor
review-after: 2026-10-17
parent-trdd: JSQSJ3PZ
---

# Spare accounts stop decaying (account B root cause, spare-age alert)

- **R8**: root-cause account B's decay (grant age, refresh cadence, revocation). Keepalive alerts when a spare's last successful refresh is older than N hours.

Parent plan: TRDD-JSQSJ3PZ

## Approval log

- 2026-10-03T03:41:36+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-03T11:22:38+0200 — column → dev. R8 code in progress
- 2026-10-03T11:52:07+0200 — column → testing. code ready; field check after release: daemon.log shows the dead spares probed every 6 h instead of every tick, and one spare-stale alarm

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

Split-out follow-ups: TRDD-L2CCH9D5 (ticks killed mid-keepalive may spend a refresh grant) and TRDD-JW8CWWNH (rotator log flooded by repeated per-tick lines).
The root-cause cure (TRDD-IT5GEZDZ, outgoing account filed at a switch) is in HEAD only and ships with the next release; until then spares keep dying on every switch.
