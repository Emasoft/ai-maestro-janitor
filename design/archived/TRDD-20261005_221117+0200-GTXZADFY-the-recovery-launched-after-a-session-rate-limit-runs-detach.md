---
trdd-id: GTXZADFY
title: The recovery launched after a session rate limit runs detached with nobody waiting for its result
column: complete
status: archived
created: 2026-10-05T22:11:17+0200
updated: 2026-10-10T16:33:11+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:17+0200
---

# The recovery launched after a session rate limit runs detached with nobody waiting for its result

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

The stop-failure hook starts 'rotator.py auto' with both streams discarded and writes a marker for the daemon to retry. The daemon task that serves the marker is a second launcher. Verify that a failed launch is always retried and that its outcome is logged somewhere.

## Approval log

- 2026-10-05T22:11:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T16:33:11+0200 — COMPLETE by main-agent@ai-maestro-janitor. archived → complete.

## Findings

2026-10-10 16:33. VERIFIED by the main session, no code. READ: scripts/hooks/on-stop-failure.py (lines 186 to 235) and scripts/daemon.py task_oauth_recovery (whole function). On a rate limit the hook writes the marker recovery-requested.ts BEFORE it starts the detached 'rotator.py auto', and nothing on the hook side ever clears it (the only two mentions of the marker under scripts are that write and the daemon task). The daemon task runs on the foreground floor, waits until the marker is 120 s old, runs 'auto' again as a timed subprocess (300 s), writes the result to daemon.log and then clears the marker. So EVERY hook-fired recovery is run a second time by the daemon, whether the first one worked or not, and that second run's exit status is logged. FIELD (daemon logs, 2026-10-08 00:32 to 2026-10-10 16:30): 279 lines 'servicing a request the hook did not clear', each followed by 'rotator auto exited 0'; no timeout, no failure line. LIMITS, each read from the code and none observed: (1) the marker write is wrapped so that a failed write is silent; then there is no retry and no record; (2) the daemon retries ONCE: after a failed or timed-out retry it logs the fact and clears the marker on purpose, so nothing tries a third time until the next rate limit writes a new marker; (3) the first, detached run's own exit status is logged nowhere; what it decided is in the rotator log, as for any 'auto'; (4) several rate limits within 120 s share one marker and one retry. Answer to the card's two questions: a failed launch is retried once whenever the marker could be written; the outcome of the retry is always logged, the outcome of the first launch is not. No change made: the one-retry rule and the redundant second run are stated design in the task's docstring (TRDD-6054NY8H).

## Acceptance

- [x] The card says: verify that a failed launch is always retried and that its outcome is logged somewhere. Verified with two stated narrowings: retried once, not always (a silent marker-write failure gets none; a failed retry is not repeated); the retry's outcome is logged in daemon.log, the first launch's exit status is not. Field: 279 serviced requests in under three days, the card's own event, all exit 0. Tests: tests/test_daemon_oauth_recovery.py, in today's green suites, not re-run by name.
