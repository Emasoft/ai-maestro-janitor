---
trdd-id: Q4V1NDS8
title: Janitor Stop hooks overrun their 10 second budget at about 12 seconds
column: todo
status: tasked
created: 2026-10-18T08:58:49+0200
updated: 2026-10-18T08:58:49+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-18T08:58:49+0200
parent-trdd: 9WPZE2NQ
---

# Janitor Stop hooks overrun their 10 second budget at about 12 seconds

Side finding of TRDD-9WPZE2NQ (reports/board/20261018_085812+0200-9wpze2nq-342-items-3-5.md), measured on this repo's transcripts over the last 7 days: scripts/hooks/on-stop.py timed out 5 times at 11469-12009 ms and once at 64334 ms; on-stop-token-meter.py 5 times at 11452-12013 ms and once at 68423 ms, both against timeout 10 in hooks/hooks.json (lines 85 and 90). The cluster at about 12.0 s suggests a fixed wait inside the hooks (INFERRED, not read); the 64-68 s outliers look like host stalls. hook-timeout-scan already records them (HOOK-001). TRDD-9TF9YXGB covers the two every-tool-call PreToolUse hooks, not these. Acceptance: the code path that takes about 12 s is identified with file:line and a timing measurement; then either a bugfix card or a reasoned budget change.

## Approval log

- 2026-10-18T08:58:49+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
