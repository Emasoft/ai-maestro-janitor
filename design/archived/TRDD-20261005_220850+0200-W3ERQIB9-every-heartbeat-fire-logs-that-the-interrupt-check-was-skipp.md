---
trdd-id: W3ERQIB9
title: Every heartbeat fire logs that the interrupt check was skipped because the session is unknown
column: complete
status: archived
created: 2026-10-05T22:08:50+0200
updated: 2026-10-09T23:19:01+0200
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
implementation-commits: [056a0be4, 8bc1d4b2]
---

# Every heartbeat fire logs that the interrupt check was skipped because the session is unknown

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed in the dispatch log of two other projects on every fire read: 'heartbeat: interrupt check skipped, session unknown'. To do: find what the check needs to know the session, why it is unknown on an ordinary fire, and what protection is lost when it is skipped.

## Approval log

- 2026-10-05T22:08:50+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T07:01:31+0200 — column → testing by main-agent@ai-maestro-janitor. batch B1-B3 merged on main, gated
2026-10-07: shipped in v3.8.4; release observation starts.
2026-10-09 CLOSED by the main session (board drain, wave 3). Checked by the main session itself: fix commits are ancestors of the v3.8.11 tag; the card's tests pass on a re-run today. Field: the card names no field observation; closed on its tests (tests/test_dispatch_phases.py, 224 passed). Not observed live: a once-per-episode log line; the newest such line in the logs predates the fix. Assessment: reports/board/20261009_231529+0200-wave3-batchA.md.
- 2026-10-09T23:19:01+0200 — COMPLETE by main-agent@ai-maestro-janitor. released in v3.8.11; tests re-run; see Approval log 2026-10-09.

## STATE

2026-10-07 merged on main (056a0be4, re-arm test 8bc1d4b2): the line is logged once per episode and logged again after a fire that has a session; read: the unknown branch returns before the reset. Not in a release yet.

## Acceptance

- [x] the card names no field observation; closed on its tests (tests/test_dispatch_phases.py, 224 passed). Not observed live: a once-per-episode log line; the newest such line in the logs predates the fix.
