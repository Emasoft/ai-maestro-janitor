---
trdd-id: KVUVV9D2
title: A resume-after-clear flag whose clear was never observed stays unarmed until the 24 h sweep
column: complete
status: archived
created: 2026-10-06T18:16:48+0200
updated: 2026-10-11T00:44:02+0200
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
2026-10-09 STAYS in testing (board drain, wave 3; fix commits are ancestors of the v3.8.11 tag and the card's tests pass on a re-run by the assessing worker). Field event not yet seen: a SessionStart where on-session-start.py ran over 5000 ms and still succeeded; the clears of 2026-10-09 on 3.8.11 are proxies because hook duration is not logged. Assessment: reports/board/20261009_232701+0200-wave3-batchF.md.
2026-10-10 DETECT (board drain step iv): NO DETECT POSSIBLE: hook duration is not logged; session-start.log has one-second stamps and no end-of-hook line, so a SessionStart over 5000 ms that still succeeded cannot be read from any file.
2026-10-10 03:48 STAY NOTE RE-CHECKED against rotated logs (board drain; reports/board/20261010_034608+0200-stay-notes-rotated-logs.md; worker-read unless marked). The step (iv) line 'NO DETECT POSSIBLE: duration not logged' is probably wrong: the findings ledger records killed hooks with their duration as HOOK-001 (8 UserPromptSubmit and 2 Stop kills in this repo's ledger, no SessionStart). CANDIDATE DETECT, unverified that the scanner sees SessionStart kills: grep HOOK-001 .janitor/state/findings-ledger.ndjsonl | grep -c SessionStart.
2026-10-10 03:49 caveat on the candidate DETECT above: a 0 is uninformative until one SessionStart kill has been seen recorded at least once (the scanner reads a transcript attachment, and a hook killed at session start may leave none); the ledger keeps 500 lines; this repo's ledger holds 20 HOOK-001 lines, of which 10 matched the 'was killed' phrasing counted above.
- 2026-10-11T00:44:02+0200 — COMPLETE by main-agent@ai-maestro-janitor. named live check met on 2026-10-10 00:55 (5644 ms, hook_success, resume cue emitted).

## STATE

2026-10-06 NEXT ACTION: none on code; wait for the named live check (a /clear on a loaded host gets clear-observed.ts stamped) after the release carrying bace60f4.
2026-10-06: root cause measured (reports/continuity-build/20261006_181911+0200-kvuvv9d2-measure.md): the 5 s SessionStart timeout killed on-session-start.py (6.7 s on a loaded host) before it stamped clear-observed.ts; the 90 s post-clear hook still injected the handoff. Fixed in bace60f4: timeout 30 s, test tests/test_session_start_hook_timeout.py. Rejected with reasons in the commit message: moving the stamp to the post-clear hook, a second writer, a dispatch fallback on a new session id. Not covered here: the model never ran the heartbeat stub in the new session (TRDD-HYTKG53C).
2026-10-06: shipped in v3.7.3 (14e56db3). The named live check needs a session started after the local update, because hooks.json is read at session start.
2026-10-06: v3.7.3 CI green and installed on the dev host (plugin update 3.7.2 -> 3.7.3).
2026-10-06: live check needs a session started after the v3.7.4 install (hooks.json is read at session start).
2026-10-07 live check (a worker's read of the logs, not re-read by the main agent): code requirement PROVEN: commit bace60f4 sets the SessionStart hook timeout to 30 s; installed hooks.json has timeout 5 in plugin cache 3.7.0, 3.7.1, 3.7.2 and timeout 30 in 3.7.3, 3.7.4, 3.7.5, 3.8.0, 3.8.1, 3.8.2; installed 3.8.2 scripts/hooks/on-session-start.py:467 still stamps clear-observed.ts. Live requirement NOT YET OBSERVABLE: every SessionStart on this project since 2026-10-05 logs the old plugin root, quote .janitor/logs/session-start.log:3595 [2026-10-07T03:52:24+0200] [s:932fc367] entered (plugin_root=<home>/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/3.7.0), 18 such entries at 3.7.0 as newest and none for 3.7.3 or later; cause: the long-lived Claude process keeps the hooks config it loaded at start and a /clear does not reload it. The latest clear did stamp clear-observed.ts (1791337944 = 2026-10-07T03:52:24+0200; hook took about 1 s, dispatch.log:6765 'post-clear resume cue emitted (age 48s)'), which does not prove the fix because a 1 s hook is under the old 5 s limit too. Original symptom: 'swept an abandoned pre-/clear resume flag' appears once, dispatch.log:3319 on 2026-09-08, none since, not discriminating. Not run: tests/test_session_start_hook_timeout.py (presence only); parent card K60FT7PJ not read. Still waits on: a restart of the Claude session (not only a /clear) so it reads the 3.7.3+ hooks.json, confirmed by the next 'entered (plugin_root=' line naming 3.7.3 or later, then a /clear where on-session-start runs over 5 s and clear-observed.ts is still stamped followed by 'post-clear resume cue emitted'.
2026-10-07 second check (a worker's read, reports/board/20261007_043810+0200-claims-and-repro176.md, gitignored): every SessionStart on this project since 2026-10-05 logged plugin root 3.7.0, including the one at 03:52:24 today; the plugin reload ran 4 seconds AFTER that SessionStart. 3.7.0's hooks.json gives SessionStart hooks 5 s, 3.7.3 and later give 30 s. Not established: whether the logged root is where the harness ran the hook from or only what the script computes, and whether a reload moves it. The next clear of that session decides: a logged root of 3.8.2 means a reload is enough, 3.7.0 means a restart is needed. See the new card on the clear-before-reload order.
FIELD EVENT FOUND by the main session, 2026-10-11 00:43 (clock), in Claude Code's own session transcripts (~/.claude/projects/<project>/<session>.jsonl): every hook run is an attachment record with hookEvent, command, type (hook_success or hook_cancelled), exitCode and durationMs. The stay notes of 2026-10-09 and 2026-10-10 that say hook duration is logged nowhere are WRONG; the check of 2026-10-07 on this card had already read these records. Counted over the 926 transcripts modified in the last 10 days, records since 2026-10-06T17:00Z for the three hooks: on-session-start.py 246, watchpaths 246, trdd-state 104, ALL hook_success, 0 hook_cancelled; over 5000 ms and successful: on-session-start.py 13 (largest 18176 ms), watchpaths 3 (8812, 6857, 6481 ms), trdd-state 0. Before the fix the same search finds 38 cancelled on-session-start.py runs (last 2026-10-05T16:01Z), 3 cancelled trdd-state and 3 cancelled watchpaths (last 2026-10-05T11:52Z). THE NAMED CHECK IS MET on this project: session 4487ea93, SessionStart:clear at 2026-10-10 00:55:54 local under plugin root 3.8.11 (session-start.log), on-session-start.py ran 5644 ms and ended hook_success (transcript), and dispatch.log has 'post-clear resume cue emitted (age 427s)' for the same session at 01:02:57, which is only emitted when the clear-observed stamp is newer than the flag. NOT shown: the stamp file's own value at that time was not read; the cue is the evidence for it. The 427 s between the clear and the cue is the wait for the next heartbeat fire, not this card's defect.

## Acceptance

- [x] The SessionStart timeout for on-session-start.py is 30 s in hooks/hooks.json and a test pins it (bace60f4, tests/test_session_start_hook_timeout.py; re-run by the assessing worker on 2026-10-09, not re-run today).
- [x] FIELD: a clear where on-session-start.py ran over 5000 ms, was not killed, and the resume cue followed (session 4487ea93, 2026-10-10 00:55, 5644 ms; one event on this project, 13 slow successful runs across all projects).
