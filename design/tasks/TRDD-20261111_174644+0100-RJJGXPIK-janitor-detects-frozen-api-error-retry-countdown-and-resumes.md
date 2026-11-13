---
trdd-id: RJJGXPIK
title: janitor detects frozen API-error retry countdown and resumes
column: testing
status: tasked
created: 2026-11-11T17:46:44+0100
updated: 2026-11-14T00:57:52+0100
current-owner: user
created-by: user
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: user
mandate: true
mandated-by: none
approved: true
approval-judge: user
approval-datetime: 2026-11-11T17:46:44+0100
relevant-rules: [1]
eht: [XVJ30M61, 7L70VR0W]
implementation-commits: [ee837c54, 88d2d9db, 07f34be0, 6ad75042, eacea9b6]
---

# janitor detects frozen API-error retry countdown and resumes

## Approval log

- 2026-11-11T17:46:44+0100 — MANDATE issued by user (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-11T17:50:24+0100 — column → dev by user. owner directive: implement freeze recovery now
- 2026-11-13T19:56:10+0100 — column → testing by main-agent@ai-maestro-janitor. implemented, gated, live-tested with seeded freeze

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-13

CURRENT (2026-11-13) — five commits, gated, fast lane live-tested with a SEEDED freeze; not released. Blocked from complete by EHT XVJ30M61 (0s banner gap). Until 6ad75042 the fast lane could be defeated in production, depending on the cadence of non-polling callers (unmeasured): any fast_lane=False scan (rotation-ESC tick, fleet-stop, cold-cache-clear, peer-freeze-recovery, fleet_status) landing between two liveness beats on a quiet in-flight turn cleared the episode, so the 100 s baseline did not survive whenever such a scan landed between two beats. The seeded live test did not show this because no other caller interleaved.

- Commits on branch fix/gitlab-cookie-review-20261105_152903: ee837c54 (ESC + resume), 88d2d9db (fast lane), 07f34be0 (3 s recheck), 6ad75042 (a non-polling scan spares the episode only for the same quiet in-flight turn, bounded by a transcript anchor within 2 s). The liveness module is committed unwired in 3a73c1b9; its wiring is blocked on TRDD-2V7OAUPE (one modules entry per plugin).
- Gates on the 6ad75042 tree (worker run): ruff, mypy (540 files), pyright clean; pytest 19056 passed 2 skipped. Follow-ups not done: the fast-lane beat's own re-baseline can still reuse a stale baseline for one beat; peer-freeze-recovery gathers with fast_lane=False, so the fast lane never runs while the daemon is dark; a multi-instance root never gets the fast lane.
- Fast lane: transcript quiet >= 60 s with a turn in flight, single-instance root, liveness beat only; frozen bar 100 s (stale lane too); injectable `now` clock; the frozen proof is confirmed by a 3 s recheck on both lanes; a rejected recheck reverts the episode, an unreadable recheck leaves it unchanged.
- Real freeze-to-ESC latency is about 3-4 min (the 88d2d9db subject '~2 beats' overstates it).
- The old line 'diagnose_instance returns healthy whenever the transcript is advancing' no longer holds: a confirmed frozen-countdown proof is diagnosed while the transcript is not stale.
- Accepted trade-offs: 3 s plus one capture per wedged instance per beat while a wedge lasts; a channel whose recheck keeps failing never confirms (the 15-min path remains).
- Unverified: a live countdown changes within 3 s (unmeasured on a real 2.1.32x pane); a natural unseeded freeze; the resume-pending retry pass (tests only).
- Open: the 0s gap, see EHT XVJ30M61. NOT released; the release-branch question (feature branch 391 commits ahead of main) is the owner's.
- NEXT ACTION: work the 0s EHT XVJ30M61; observe one natural freeze recovered live after a release.
eacea9b6 (2026-11-13): anchor key renamed to transcript_instant (substantive-row instant, never st_mtime). An old state carrying only transcript_mtime has no int anchor, so it is not spared (fleet_scan.py:1412-1414) and the caller clears it (fleet_scan.py:1668-1681), fail-safe. Tests added: an interrupt row after a sent resume clears the episode (two cases, mutation-checked, worker-reported), and a queue-row storm that pushes the prompt out of the 64 KiB tail clears it. Full suite after eacea9b6: 19060 passed, 2 skipped. Open follow-ups, not carded yet: one-beat re-baseline hazard; peer-freeze-recovery and multi-instance roots get no fast lane.
