---
trdd-id: K60FT7PJ
title: An idle session after a clear or compaction is never woken because quiet heartbeats do nothing and two clear paths emit no resume cue
column: todo
status: tasked
created: 2026-10-06T16:49:44+0200
updated: 2026-10-06T17:25:51+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T16:49:44+0200
---

# An idle session after a clear or compaction is never woken because quiet heartbeats do nothing and two clear paths emit no resume cue

Measured 2026-10-06, report reports/continuity-build/20261006_164603+0200-idle-after-resume-measure.md (gitignored; facts restated here). Three causes left agents idle after a clear or compaction:

(A) The janitor-clear NEXT ACTION said "ask it again and stop" (scripts/lib/session_continuity.py next_action); a resumed session re-asked its question and idled 29 min through five [janitor-quiet] fires, each answered exactly "janitor heartbeat" as the heartbeat protocol rule requires. Wording fixed separately (see implementation-commits of TRDD-DS3WDTPV); the no-wake layer remains: a quiet fire never re-engages an idle session that still has in-flight work.

(B) WEBDESIGN session: a resumed-cold clear fired 1 s after a startup SessionStart; the clear chain logged "FAILED - /clear submitted but no fresh session within 180s"; the clear landed 6 min later; on-session-start.py (~:1517) logged "source=clear keeps the live cron -> no re-arm", but no live cron existed (the startup re-arm never ran). No heartbeat ran, resume-after-clear.flag stayed unconsumed; idle 46 min until the user typed /janitor-arm.

(C) ORCHESTRATOR session: clear-observed.ts was never re-stamped (no SessionStart log line for the clear), so dispatch.py _phase_clear_resume (~:2024-2036, observed_at < written_at) never armed the cue; the flag is still on disk; the agent idled 53 min through quiet fires and resumed only by overriding the quiet-fire rule.

To do: design (with the advisor) and fix: a quiet fire that finds an unconsumed resume flag, or an idle session with in-flight work, must emit a resume cue instead of [janitor-quiet]; a source=clear SessionStart must not assume a live cron; an unobserved clear must not leave the flag unarmed forever. Each fix gets a test that fails before it, and a named live check.

## Approval log

- 2026-10-06T16:49:44+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-06 review (a): This card holds three tasks (quiet-fire wake, source=clear assuming a live cron, unobserved clear); split into three derived cards before dev, one task each.
2026-10-06 review (b): Cause B overstated: "no live cron existed (the startup's re-arm never ran)" is INFERRED; measured only that the recorded cron id was gone when /janitor-arm ran later.
2026-10-06 review (c): Cause C co-cause: SessionStart did run and inject the handoff (the agent quoted "ask it again and stop"), so the clear-observed stamp was the missing part, and the old wording (fixed in 10a763b8) contributed to the 53 min idle.
2026-10-06 review (d): Check first whether the daemon's session-liveness guardian (task_session_liveness) or TRDD-L32WC0H7 already owns noticing a session whose heartbeat stopped (cause B); if so this is that guardian's defect.
2026-10-06 review (e): Any quiet-fire wake also changes the shipped rule rules/janitor-heartbeat-protocol.md (quiet fire = reply only "janitor heartbeat", no tool calls).
2026-10-06 review (f): Case D (not yet carded elsewhere): the NEXT ACTION can quote the /janitor-arm chatter as "your reply" instead of the substantive reply, which now also makes "was a task in flight" harder to judge.
2026-10-06 review (g): The To-do should state the problem, not the mechanism; the fix design goes through the advisor first.
