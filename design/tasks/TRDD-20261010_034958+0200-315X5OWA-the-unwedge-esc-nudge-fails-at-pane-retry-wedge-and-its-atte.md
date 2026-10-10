---
trdd-id: 315X5OWA
title: The unwedge ESC nudge fails at pane retry_wedge and its attempts climb with no recovery
column: todo
status: tasked
created: 2026-10-10T03:49:58+0200
updated: 2026-10-10T03:51:17+0200
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
2026-10-10 03:51 CORRECTION to the body (review of af8d1b1e; lines read by the main session): the 10 '[frozen] attempt=' lines are 5 pairs, an 'unwedge: failed' pane-policy line and then a 'FIRE-FAILED esc_nudge' line in the same second. That is 5 failed fires in TWO episodes, not five episodes: ai-maestro at 19:21:26, 19:40:46 and 19:56:23 (attempts 0, 1, 2) and llm-externalizer at 19:30:06 and 19:45:13 (attempts 0, 1), all 2026-10-09. No other FIRE-FAILED esc_nudge line is in the logs on disk. The file and line daemon.py:1602 is worker-read; the session-liveness FIRE-FAILED line is built at daemon.py:2108 (grep hit).
