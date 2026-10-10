---
trdd-id: 315X5OWA
title: The unwedge ESC nudge fails at pane retry_wedge and its attempts climb with no recovery
column: todo
status: tasked
created: 2026-10-10T03:49:58+0200
updated: 2026-10-10T03:49:58+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T03:49:58+0200
---

# The unwedge ESC nudge fails at pane retry_wedge and its attempts climb with no recovery

Goal: investigate, verify and fix the root cause. Found on 2026-10-10 by the board drain (TRDD-S6GX1DHN, step vi); not investigated beyond what is written here. Read in global-state/daemon.log: 10 lines containing '[frozen] attempt=' between 2026-10-09T19:21:26 and 19:56:23 (count by the main session); a worker read them as 5 episodes in two other projects (ai-maestro, llm-externalizer), each 'FIRE-FAILED esc_nudge' at pane=retry_wedge followed by 'unwedge: failed', attempts 0, 1, 2. The line is written at scripts/daemon.py:1602. Related: TRDD-L32WC0H7 (its success case is unseen), TRDD-WKTD5JTC (wedge detection, complete), TRDD-KE88RIKX. To do: read why the fire fails (typing gate, pane kind, or the injector itself), and whether a third failed attempt should change remedy.

## Approval log

- 2026-10-10T03:49:58+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
