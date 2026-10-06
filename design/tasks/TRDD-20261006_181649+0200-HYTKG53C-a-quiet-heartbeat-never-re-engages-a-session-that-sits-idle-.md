---
trdd-id: HYTKG53C
title: A quiet heartbeat never re-engages a session that sits idle with work still in flight
column: testing
status: tasked
created: 2026-10-06T18:16:49+0200
updated: 2026-10-06T19:23:50+0200
current-owner: main-agent@ai-maestro-janitor
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
derived: true
derived-kind: eht
implementation-commits: [79255d6e]
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

2026-10-06 (superseded by the line below): design with the advisor.
2026-10-06: ROOT CAUSE found by the advisor and verified in dispatch.log: the wake already exists (_phase_keep_going_nudge, dispatch.py ~3767-3972) but its user-idle check read the machine-global presence file, which a prompt in ANY session bumps, so every session's nudge was muted while the owner typed anywhere (2530 "keep-going: suppressed (user active" lines; all five quiet fires of the 29 min idle). Fixed in 79255d6e: both presence readers use the per-pane file when a pane key resolves (absent = idle, no global fallback), global only with no pane id. No new detector, no heartbeat-rule change, no new token. NEXT ACTION: none on code. NAMED LIVE CHECK after the release carrying 79255d6e: with the owner typing in another pane, an idle session whose last reply ended on a question gets [janitor-resume] within two fires and dispatch.log shows a keep-going line without "suppressed (user active"; also check one session in another project and note any nudge onto a card it does not own.
2026-10-06: shipped in v3.7.5 (carries 79255d6e). The owner was told of the same-project collision risk (TRDD-LH84WTL5) before publishing and had not replied; the release went out on the standing "publish as soon as possible" instruction for the resume problem. Caveat for the live check: task-notification turns count as user presence (the hook filters only [janitor-...] prompts), so a session whose background agents keep reporting will still log "suppressed (user active"; run the check in a quiet session in another pane (e.g. the WEBDESIGN or ORCHESTRATOR agent session) while the owner types elsewhere.
