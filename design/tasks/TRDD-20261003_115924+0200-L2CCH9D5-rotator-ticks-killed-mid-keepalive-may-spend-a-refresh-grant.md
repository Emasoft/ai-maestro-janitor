---
trdd-id: L2CCH9D5
title: Rotator ticks killed mid-keepalive may spend a refresh grant without storing it
column: backburner
status: tasked
created: 2026-10-03T11:59:24+0200
updated: 2026-10-03T11:59:24+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: user
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T11:59:24+0200
parent-trdd: JSQSJ3PZ
---

# Rotator ticks killed mid-keepalive may spend a refresh grant without storing it

On 2026-10-01 to 10-03 daemon.log shows 33 rotator ticks killed at 135-148 s (2-5 per hour in the 10-02 evening). Keepalive is the first heavy step of cmd_tick. The token endpoint rotates refresh tokens, so a tick killed after the HTTP reply and before write_slot spends the grant without storing the new one. This is hypothesis H4 of the R8 report: not refuted, no instance proven.

Proposed: run keepalive per slot with a per-call timeout well below the tick timeout and write each refreshed slot immediately; find why ticks reach 135-148 s (keychain latch under load).

Evidence: local report reports/oauth-rotator/20261003_111621+0200-R8-spare-decay-root-cause.md (gitignored, local only).

Related: TRDD-B78NJU35, TRDD-ZAKT0NRI.

## Approval log

- 2026-10-03T11:59:24+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
