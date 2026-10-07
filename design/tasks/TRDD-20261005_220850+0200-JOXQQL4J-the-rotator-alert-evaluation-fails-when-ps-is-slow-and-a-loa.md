---
trdd-id: JOXQQL4J
title: The rotator alert evaluation fails when ps is slow and a load stall is reported as a stopped rotator
column: dev
status: tasked
created: 2026-10-05T22:08:50+0200
updated: 2026-10-07T04:34:41+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:50+0200
---

# The rotator alert evaluation fails when ps is slow and a load stall is reported as a stopped rotator

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed under very high load: the daemon logged 'rotator-alert: evaluation failed: Command ps -eo args= timed out after 10 seconds', one rotator tick took 717 s, and the next heartbeat showed 'the account rotator has stopped ticking - run /janitor-doctor' although the rotator ticked normally a minute later. To do: decide what the alert evaluation does when ps is slow (the evaluation is lost exactly when the host is in trouble), and whether a single late tick under load deserves the doctor remedy. Related: TRDD-JY0OBQZ4.

## Approval log

- 2026-10-05T22:08:50+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T04:31:38+0200 — column → dev by main-agent@ai-maestro-janitor. fix is on a worktree branch, not merged yet

## STATE

2026-10-07 investigation (reports/board/20261007_042322+0200-rotator-ps-timeout-and-stderr-tail.md, gitignored; facts copied here): the only ps -eo args= call is claude_running() in scripts/oauth_rotator/rotator.py. It has three callers: the tick guard in cmd_tick, the guard in cmd_capture, and the daemon alert evaluation. Measured in about 52 hours of daemon logs: 10 timeouts, 2 in the tick (2026-10-05 14:41:58 and 15:56:37, each losing the whole tick, and the single retry hit the same timeout) and 8 in the alert evaluation (2026-10-05 06:02:40, 06:09:08, 13:25:51, 21:33:28; 2026-10-06 16:00:55, 17:00:10, 21:07:17, 21:21:24). Scope widened to the lost tick.
2026-10-07 DECISION by the main agent (owner ruling 'decide yourself' applies; reversible): on a ps timeout claude_running() prints one stderr line and returns True. Reason: the guard only answers whether there is anything to do; a wrong True costs one idempotent, lock-guarded tick, a raise costs the whole beat exactly when the host is loaded. This is a deliberate exception to the fail-fast rule. In the alert path the flag gates only the no-rotation-target, spare-stale and tick-stalled conditions (rotator_alert.active_conditions, read by the main agent), which are evaluated on every normal beat while Claude runs, so a stalled ps now evaluates them where it used to skip. In cmd_capture the flag is only the same silent no-op guard. The advisor was not consulted: its agent type is absent from the session's agent list after a plugin reload, and no built-in advisor tool exists in this session. STILL OPEN on this card: whether one late tick under load deserves the tick-stalled alarm and the doctor remedy (TICK_STALL_S against measured tick durations). Code is on a worktree branch, not merged yet.
