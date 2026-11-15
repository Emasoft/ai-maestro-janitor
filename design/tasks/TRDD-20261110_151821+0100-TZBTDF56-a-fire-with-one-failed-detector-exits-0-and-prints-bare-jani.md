---
trdd-id: TZBTDF56
title: a fire with one failed detector exits 0 and prints bare janitor-quiet
column: testing
status: tasked
created: 2026-11-10T15:18:21+0100
updated: 2026-11-15T21:32:14+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-10T15:18:21+0100
---

# a fire with one failed detector exits 0 and prints bare janitor-quiet

From issue #342 (tier E of the 2026-11-10 reconciliation on FQVEILVK): when a detector exits non-zero or times out, dispatch.py records error:rc=N in the streak stamp and ledger, re-emits the detector's defanged stderr (which may be a traceback, a compact line, or empty depending on what the detector printed), but main() still returns 0 and _emit_quiet_if_idle prints a bare [janitor-quiet]. A partially-failed fire is indistinguishable from a clean pass by exit code and marker; the degraded fact lives only in the ledger stamp and stderr. Fix must preserve TRDD-P64SR014's noise dedupe (3-streak batching) while making the degraded state observable per-fire without a full traceback; candidate shapes: a [janitor-degraded] marker naming the detector (requires a matching heartbeat-protocol rule row), or one concise stdout drift line per failing detector. Design choice needs the owner or a proposal.

## Approval log

- 2026-11-10T15:18:21+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-11T07:11:54+0100 — column → testing by main-agent@ai-maestro-janitor. fix implemented in a1e0b8a3; 3 new tests pass; ruff+mypy clean; existing quiet/streak tests pass

## STATE

2026-11-11: fix implemented in a1e0b8a3. _fire_degraded list appended in _track_detector_streak (single chokepoint), printed by _emit_quiet_if_idle after [janitor-quiet] and after _phase_background_worker_progress. 3 new tests in test_dispatch_phases.py pass; ruff+mypy clean; existing quiet/streak tests pass. Card in testing pending full suite run before publish.
2026-11-15 FOLLOW-UP for #342: a1e0b8a3 printed the degraded: line on EVERY fire while a detector kept failing (ticket-dispatch runs every 300 s). DECIDED by the main agent under the owner's standing 'decide yourself' (TRDD-S6GX1DHN, 2026-10-09): KEEP the line, fed only when the failure state changes (the first failure of an episode, or a different outcome from the previous pass), with the suffix '(informational; not a task - do not investigate unless asked)'. Alternative weighed, DELETE (drop the line; the HIGH DETECTOR-FAIL ledger row at the 3rd pass stays the only signal): rejected because #342 item 2 asks that a partly failed fire stay distinguishable from a clean pass. UNTESTED until the pre-push suite: two new tests and one edited test in tests/test_dispatch_phases.py. Edge behaviours with no test: a stamp read error announces the failure on every pass; an error from state_dir() skips the announcement. Plan: reports_dev/fanout-research/20261115_204105+0100-heartbeat-noise-plan.md; apply report: reports_dev/fanout-apply/20261115_205511+0100-heartbeat-noise-apply.md (both local, gitignored).
2026-11-15 #342 follow-up committed in 112cf17e and 726f2c74: the outer except of _track_detector_streak now announces an error outcome that a state error would have hidden. Mutation run (reported in the 726f2c74 commit message, not re-run here): with the new except body replaced by pass, test_track_detector_streak_announces_when_the_stamp_cannot_be_written fails (1 failed), so that test guards the fix; the sibling test guards only the no-double-entry check and asserts the stamp write failed.
