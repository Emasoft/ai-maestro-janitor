---
trdd-id: 393Z256I
title: Session-liveness gives up on a cron_dead session after four attempts and asks for a human who is not there
column: testing
status: tasked
created: 2026-10-10T03:49:59+0200
updated: 2026-10-17T02:00:05+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T03:49:59+0200
implementation-commits: [59fb90d0]
---

# Session-liveness gives up on a cron_dead session after four attempts and asks for a human who is not there

Goal: investigate, verify and fix the root cause. Found on 2026-10-10 by the board drain (TRDD-S6GX1DHN, step vi); not investigated beyond what is written here. Read by the main session in global-state/daemon.log and daemon.log.1: 'session-liveness: GIVING UP on ai-maestro-janitor [cron_dead] attempt=4 after 4 attempts — recovery is looping; a human must intervene' at 2026-10-08T02:04:35 and 2026-10-09T20:14:40, and the same line for AgentlensPro at 2026-10-09T20:30:03. Not read: what the four attempts did, whether the session recovered by itself afterwards, and whether anything tells the owner. To do: read the attempts before each line, decide what the daemon should do when recovery loops on an unattended host. Related: TRDD-L32WC0H7, TRDD-FB84YUGT.

## Approval log

- 2026-10-10T03:49:59+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-10 03:51 CORRECTION (review of af8d1b1e): the title's 'a human who is not there' is not read from anything; the log line only says a human must intervene. TRDD-FB84YUGT, cited as related, exists (archived); it was not read.
2026-10-10 04:12 CORRECTION to the line above: TRDD-FB84YUGT is in design/tasks, not archived.
- 2026-10-17T02:00:04+0200 — BUILT in 59fb90d0. Root cause: the WEDGED short-circuit spent an attempt per beat while typing nothing, so four beats reached crash_loop and logged 'GIVING UP ... recovery is looping' with zero fired rows (5 episodes 10-08..10-10, from the HMAC recovery audit; the daemon.log lines had rotated). It now declines through _decline (no attempt; FLEET-WEDGED once; FLEET-DECLINE-STALL once after 1 h with a declined_wedged remedy). Deliberately reverses TRDD-8DR0X08A db9c2f01, whose purpose (an eventual alert) feddf82b now serves. Cannot tell from the rotated logs whether the sessions were in a long turn or on a dialog; correct under both. 51 tests pass; ruff, mypy, pyright clean. Split: TRDD-366Y1OUH (non-frozen give-up writes no finding). FIELD CHECK: the next wedged episode after a release shows no GIVING UP and one FLEET-DECLINE-STALL if it lasts an hour.
