---
trdd-id: K4A4JI67
title: Root-cause the 00.38 Login expired on account A
column: todo
status: tasked
created: 2026-10-03T03:40:47+0200
updated: 2026-10-03T03:41:02+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:40:47+0200
project-id: ai-maestro-janitor
parent-trdd: JSQSJ3PZ
---

# Root-cause the 00.38 Login expired on account A

**R0 (worker, read-only).** Separate the three hypotheses.
1. Search the `fd932daa` transcript and `~/.claude/debug/` for Claude Code's refresh error text around 00:30–00:40: `invalid_grant` vs. a timeout.
2. Search `rotator.log`/`daemon.log` for any janitor touch of account A's grant between 16:42 (its last keepalive refresh) and 00:38, especially `_refresh_and_heal_slot` after the 19:26 switch.
3. Check whether a running Claude Code picks up a credential switched into the keychain after "Login expired", or needs `/login`. Look at the binary strings for the 401 handling path.
- **Verify**: a one-line verdict with evidence for each hypothesis, written to R0. If the evidence cannot separate them, say so; R1–R3 still ship.

Parent plan: TRDD-JSQSJ3PZ

## Approval log

- 2026-10-03T03:40:47+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
