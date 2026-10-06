---
trdd-id: KVUVV9D2
title: A resume-after-clear flag whose clear was never observed stays unarmed until the 24 h sweep
column: todo
status: tasked
created: 2026-10-06T18:16:48+0200
updated: 2026-10-06T18:16:54+0200
current-owner: lean-worker#cd372946-645f-4e16-a8a0-7013e0d8c5b6
created-by: lean-worker#cd372946-645f-4e16-a8a0-7013e0d8c5b6
task-type: bugfix
min-approval-requirement: none
assignee: lean-worker#cd372946-645f-4e16-a8a0-7013e0d8c5b6
mandate: true
mandated-by: none
approved: true
approval-judge: lean-worker#cd372946-645f-4e16-a8a0-7013e0d8c5b6
approval-datetime: 2026-10-06T18:16:48+0200
parent-trdd: K60FT7PJ
---

# A resume-after-clear flag whose clear was never observed stays unarmed until the 24 h sweep

## Problem
A resume-after-clear flag whose /clear was never observed (no clear-observed stamp newer than the flag) is treated as NOT armed, so no resume cue is emitted until the 24 h age sweep unlinks it as abandoned. A clear that DID happen but was not stamped is thereby treated as abandoned.

## Evidence (from reports/continuity-build/20261006_180000+0200-k60ft7pj-ownership-measure.md)
- VERIFIED dispatch.py:2027-2060 _phase_clear_resume: arming test 'observed_at <= 0 or observed_at < written_at' -> NOT armed; the branch only sweeps by age (CLEAR_RESUME_MAX_AGE_S default 86400 s) and logs 'swept an abandoned pre-/clear resume flag'.
- VERIFIED on-session-start.py:986 stamps clear-observed only for source=clear (plus the startup-chain-clear service, TRDD-C7M4RXQ2).
- VERIFIED ORCHESTRATOR 2026-10-05 sat idle 53 min under this path.
- INFERRED/not re-verified: whether the ORCHESTRATOR run missed the stamp (no SessionStart log line was examined).

## Approval log

- 2026-10-06T18:16:48+0200 — MANDATE issued by lean-worker#cd372946-645f-4e16-a8a0-7013e0d8c5b6 (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

NEXT ACTION (2026-10-06, go first): write a failing test for _phase_clear_resume where the flag is older than a few minutes, clear-observed is older than the flag, and the session transcript is newer than the flag (evidence the clear happened); then propose the minimal fix in that NOT-armed branch.
