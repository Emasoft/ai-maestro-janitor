---
trdd-id: V2U2ZECI
title: A swallowed fire-epoch log write leaves no trace, so a fire that ran looks like a fire that never happened
column: todo
created: 2026-09-16T12:54:50+0200
updated: 2026-09-16T12:54:50+0200
current-owner: session
created-by: session
task-type: bugfix
min-approval-requirement: none
assignee: session
mandate: true
mandated-by: none
approved: true
approval-judge: session
approval-datetime: 2026-09-16T12:54:50+0200
---

# A swallowed fire-epoch log write leaves no trace, so a fire that ran looks like a fire that never happened

Observed 2026-09-16 12:47 local: the first cron fire after the local plugin rolled 3.5.4 to 3.5.5 printed [janitor-quiet] but appended no fire epoch line to .janitor/logs/heartbeat-fires.log and no line to dispatch.log; the next five fires logged normally (report reports/board-drain/20260916_125217+0200-silent-355-fires.md). Cause per the read-only diagnosis: the fire-log append sits in a fail-open try/except that swallows the exception with no stderr line, and the likely trigger was a filesystem race with the concurrent plugin-cache version swap. Fail-open is right (telemetry must never block a fire); silence is not: an unlogged fire is indistinguishable from a stub that never ran, the exact ambiguity _emit_quiet_if_idle exists to remove. Fix: on the swallowed exception write one line to stderr and, if possible, one state.log_line naming the exception type, mirroring TRDD-9EAQS97B's trace for run_subprocess. Acceptance: (1) a test that makes the fire-log path unwritable asserts the fire still completes and stderr carries one line naming the failure; (2) ruff/mypy/pyright clean; (3) no change to the quiet-token contract.

## Approval log

- 2026-09-16T12:54:50+0200 — MANDATE issued by session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
