---
trdd-id: HYTKG53C
title: A quiet heartbeat never re-engages a session that sits idle with work still in flight
column: todo
status: tasked
created: 2026-10-06T18:16:49+0200
updated: 2026-10-06T18:16:55+0200
current-owner: lean-worker#cd372946-645f-4e16-a8a0-7013e0d8c5b6
created-by: lean-worker#cd372946-645f-4e16-a8a0-7013e0d8c5b6
task-type: bugfix
min-approval-requirement: none
assignee: lean-worker#cd372946-645f-4e16-a8a0-7013e0d8c5b6
mandate: true
mandated-by: none
approved: true
approval-judge: lean-worker#cd372946-645f-4e16-a8a0-7013e0d8c5b6
approval-datetime: 2026-10-06T18:16:49+0200
parent-trdd: K60FT7PJ
---

# A quiet heartbeat never re-engages a session that sits idle with work still in flight

## Problem
A quiet heartbeat fire makes the session reply only 'janitor heartbeat' with no tool calls, so a session that sits idle with work still in flight is never re-engaged. Idle-after-quiet is compliant behavior under the shipped rule, not agent misbehavior.

## Evidence (from reports/continuity-build/20261006_180000+0200-k60ft7pj-ownership-measure.md)
- VERIFIED dispatch.py:1055-1073 _emit_quiet_if_idle prints [janitor-quiet] iff no action decision fired (called from the terminal no-action exit ~4574).
- VERIFIED dispatch.py ~1541 _phase_background_worker_progress prints a note only for in-flight background workers (TRDD-I63GQJTK); no-op for an idle session.
- VERIFIED rules/janitor-heartbeat-protocol.md:21-27 (reply exactly 'janitor heartbeat', no tool calls) and :42 (table row).
- VERIFIED no existing phase detects 'idle with in-flight work'; resume flags are consumed only by the compact/clear resume phases and sweepers.
- Observed 2026-10-06: a 29 min idle case. The guardian cannot see it: the transcript advances on each quiet fire, so the session reads as healthy.
- Any cue must use the existing [janitor-resume] token or the rule text must change. Cheap interim: _emit_quiet_if_idle emits [janitor-resume] when an unconsumed resume flag exists (overlaps card 1).

## Approval log

- 2026-10-06T18:16:49+0200 — MANDATE issued by lean-worker#cd372946-645f-4e16-a8a0-7013e0d8c5b6 (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

NEXT ACTION (2026-10-06, last): design with the advisor; the cue must respect RULE 1 (only work already assigned) and the owner's cost concerns (each wake is a full model turn).
