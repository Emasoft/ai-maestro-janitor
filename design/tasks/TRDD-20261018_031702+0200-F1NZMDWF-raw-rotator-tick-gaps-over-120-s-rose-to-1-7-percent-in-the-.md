---
trdd-id: F1NZMDWF
title: Raw rotator tick gaps over 120 s rose to 1.7 percent in the 2026-10-16 to 18 window
column: todo
status: tasked
created: 2026-10-18T03:17:02+0200
updated: 2026-10-18T03:17:02+0200
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
approval-datetime: 2026-10-18T03:17:02+0200
---

# Raw rotator tick gaps over 120 s rose to 1.7 percent in the 2026-10-16 to 18 window

Found while re-measuring TRDD-QJ5LP4W2 box 4 on 2026-10-18 (worker-read report docs_dev/20261018_031558+0200-QJ5LP4W2-box4-measure.md). Over 47.85 h of daemon.log.1 + daemon.log, 42 of 2590 oauth-rotator-tick gaps exceeded 120 s (1.7 percent, max 249 s, clustered 10-16 07:11-07:20 and 10-17 18:32, 22:37-23:31), against 0.08 percent measured after 3.7.0 on 2026-10-05; card-method stalls (body subtracted) were 0, so the per-beat budget holds. To do: attribute the long gaps (cold-cache-clear bodies of about 200 s and a 231 s session-liveness body precede the 10-16 cluster), and check whether the TRDD-JY0OBQZ4 slow-tick lines (after a release) explain them. Acceptance: each gap cluster attributed to a named task or cause, or a recorded reason it cannot be.

## Approval log

- 2026-10-18T03:17:02+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
