---
trdd-id: KVUVV9D2
title: A resume-after-clear flag whose clear was never observed stays unarmed until the 24 h sweep
column: testing
status: tasked
created: 2026-10-06T18:16:48+0200
updated: 2026-10-07T04:44:31+0200
current-owner: main-agent@ai-maestro-janitor
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
derived: true
derived-kind: eht
implementation-commits: [bace60f4]
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

2026-10-06 NEXT ACTION: none on code; wait for the named live check (a /clear on a loaded host gets clear-observed.ts stamped) after the release carrying bace60f4.
2026-10-06: root cause measured (reports/continuity-build/20261006_181911+0200-kvuvv9d2-measure.md): the 5 s SessionStart timeout killed on-session-start.py (6.7 s on a loaded host) before it stamped clear-observed.ts; the 90 s post-clear hook still injected the handoff. Fixed in bace60f4: timeout 30 s, test tests/test_session_start_hook_timeout.py. Rejected with reasons in the commit message: moving the stamp to the post-clear hook, a second writer, a dispatch fallback on a new session id. Not covered here: the model never ran the heartbeat stub in the new session (TRDD-HYTKG53C).
2026-10-06: shipped in v3.7.3 (14e56db3). The named live check needs a session started after the local update, because hooks.json is read at session start.
2026-10-06: v3.7.3 CI green and installed on the dev host (plugin update 3.7.2 -> 3.7.3).
2026-10-06: live check needs a session started after the v3.7.4 install (hooks.json is read at session start).
2026-10-07 live check (a worker's read of the logs, not re-read by the main agent): code requirement PROVEN: commit bace60f4 sets the SessionStart hook timeout to 30 s; installed hooks.json has timeout 5 in plugin cache 3.7.0, 3.7.1, 3.7.2 and timeout 30 in 3.7.3, 3.7.4, 3.7.5, 3.8.0, 3.8.1, 3.8.2; installed 3.8.2 scripts/hooks/on-session-start.py:467 still stamps clear-observed.ts. Live requirement NOT YET OBSERVABLE: every SessionStart on this project since 2026-10-05 logs the old plugin root, quote .janitor/logs/session-start.log:3595 [2026-10-07T03:52:24+0200] [s:932fc367] entered (plugin_root=<home>/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/3.7.0), 18 such entries at 3.7.0 as newest and none for 3.7.3 or later; cause: the long-lived Claude process keeps the hooks config it loaded at start and a /clear does not reload it. The latest clear did stamp clear-observed.ts (1791337944 = 2026-10-07T03:52:24+0200; hook took about 1 s, dispatch.log:6765 'post-clear resume cue emitted (age 48s)'), which does not prove the fix because a 1 s hook is under the old 5 s limit too. Original symptom: 'swept an abandoned pre-/clear resume flag' appears once, dispatch.log:3319 on 2026-09-08, none since, not discriminating. Not run: tests/test_session_start_hook_timeout.py (presence only); parent card K60FT7PJ not read. Still waits on: a restart of the Claude session (not only a /clear) so it reads the 3.7.3+ hooks.json, confirmed by the next 'entered (plugin_root=' line naming 3.7.3 or later, then a /clear where on-session-start runs over 5 s and clear-observed.ts is still stamped followed by 'post-clear resume cue emitted'.
2026-10-07 second check (a worker's read, reports/board/20261007_043810+0200-claims-and-repro176.md, gitignored): every SessionStart on this project since 2026-10-05 logged plugin root 3.7.0, including the one at 03:52:24 today; the plugin reload ran 4 seconds AFTER that SessionStart. 3.7.0's hooks.json gives SessionStart hooks 5 s, 3.7.3 and later give 30 s. Not established: whether the logged root is where the harness ran the hook from or only what the script computes, and whether a reload moves it. The next clear of that session decides: a logged root of 3.8.2 means a reload is enough, 3.7.0 means a restart is needed. See the new card on the clear-before-reload order.
