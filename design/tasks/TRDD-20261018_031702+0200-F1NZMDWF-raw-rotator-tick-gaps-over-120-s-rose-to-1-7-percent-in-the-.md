---
trdd-id: F1NZMDWF
title: Raw rotator tick gaps over 120 s rose to 1.7 percent in the 2026-10-16 to 18 window
column: blocked
status: tasked
created: 2026-10-18T03:17:02+0200
updated: 2026-10-18T03:17:59+0200
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
blocked-by: [JY0OBQZ4]
pre-block-column: todo
---

# Raw rotator tick gaps over 120 s rose to 1.7 percent in the 2026-10-16 to 18 window

Found while re-measuring TRDD-QJ5LP4W2 box 4 on 2026-10-18 (worker-read report docs_dev/20261018_031558+0200-QJ5LP4W2-box4-measure.md). Over 47.85 h of daemon.log.1 + daemon.log, 42 of 2590 oauth-rotator-tick gaps exceeded 120 s (1.7 percent, max 249 s, clustered 10-16 07:11-07:20 and 10-17 18:32, 22:37-23:31), against 0.08 percent measured after 3.7.0 on 2026-10-05; card-method stalls (body subtracted) were 0, so the per-beat budget holds. To do: attribute the long gaps (cold-cache-clear bodies of about 200 s and a 231 s session-liveness body precede the 10-16 cluster), and check whether the TRDD-JY0OBQZ4 slow-tick lines (after a release) explain them. Acceptance: each gap cluster attributed to a named task or cause, or a recorded reason it cannot be.

## Approval log

- 2026-10-18T03:17:02+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-18T03:17:59+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on TRDD-JY0OBQZ4's slow-tick lines after a release

## Notes

2026-10-18 (review of 0e51cc62): LIKELY THE SAME CAUSE AS TRDD-JY0OBQZ4. A rotator gap is the previous tick's body plus the 60 s cadence; JY0OBQZ4 measured rotator ticks of 30 s or more on 3 to 6 percent of runs, max 188 s, and 188 + 60 = 248 s matches the 247 to 249 s gaps here. So the 1.7 percent is probably slow rotator bodies, not occupancy by other tasks (card-method stalls, which subtract the body, are 0). JY0OBQZ4's 'rotator tick slow:' lines (b1870adb, after a release) will attribute them; until then this card waits on it. The first cluster (10-16 07:11 to 07:20) is BEFORE the 12:21 restart, whose build is unknown.
CORRECTIONS to the archived TRDD-QJ5LP4W2 closure, recorded here because that card is frozen: (a) its box 4 'stall count falling' has no same-method baseline in this window (the earlier 39/472 and 1/1312 are raw gaps over 120 s, not card-method stalls); the honest reading is 'card-method stalls stay at 0'. (b) Its budget-exceeded conclusion rests on the 38.55 h after the 10-16 restart only; the 8.95 h before it ran at 11.8/h, worse than before 3.7.0, on an unknown build.
