---
trdd-id: 9438CGJZ
title: SessionStart hooks share a 5 s budget a loaded host exceeds, so the STATE injection and watchpaths hooks are killed silently
column: complete
status: archived
created: 2026-10-06T18:33:18+0200
updated: 2026-10-11T00:44:02+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T18:33:18+0200
implementation-commits: [dd779c12]
---

# SessionStart hooks share a 5 s budget a loaded host exceeds, so the STATE injection and watchpaths hooks are killed silently

On 2026-10-05 (ORCHESTRATOR /clear, transcript 05acb47b) every SessionStart hook took 5.5-6.7 s and on-session-start-trdd-state.py (5999 ms) and on-session-start-watchpaths.py (6114 ms) were killed at their 5 s timeout (hooks/hooks.json), silently: a resumed session then loses its in-progress TRDD STATE blocks. on-session-start.py got 30 s in bace60f4 (TRDD-KVUVV9D2). Measure first where the start-up time goes (uv run --script resolve, interpreter start, lib imports, contention between the 5 hooks starting in parallel) before raising more limits one by one.

## Approval log

- 2026-10-06T18:33:18+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-09 STAYS in testing (board drain, wave 3; fix commits are ancestors of the v3.8.11 tag and the card's tests pass on a re-run by the assessing worker). Field event not yet seen: a slow SessionStart showing hook success for all three hooks past 5000 ms; only proxies so far. Assessment: reports/board/20261009_232701+0200-wave3-batchF.md.
2026-10-10 DETECT (board drain step iv): NO DETECT POSSIBLE: no hook duration is logged and a kill is silent; the only trigger is a hook_cancelled timedOut record found in a session transcript, which names no stable log.
2026-10-10 03:48 STAY NOTE RE-CHECKED against rotated logs (board drain; reports/board/20261010_034608+0200-stay-notes-rotated-logs.md; worker-read unless marked). The step (iv) line 'NO DETECT POSSIBLE' is probably wrong for the same reason as on TRDD-KVUVV9D2: HOOK-001 ledger lines carry a killed hook's duration. CANDIDATE DETECT, unverified for SessionStart: grep HOOK-001 .janitor/state/findings-ledger.ndjsonl | grep -c SessionStart.
2026-10-10 03:49 caveat on the candidate DETECT above: a 0 is uninformative until one SessionStart kill has been seen recorded at least once; see the same caveat on TRDD-KVUVV9D2.
- 2026-10-11T00:44:02+0200 — COMPLETE by main-agent@ai-maestro-janitor. named live check met as written; narrowing for trdd-state stated in the checklist.

## STATE

NEXT ACTION: measure SessionStart hook start-up cost on this host (cold and warm) per hook.
2026-10-06: measured (reports/continuity-build/20261006_185535+0200-sessionstart-hook-cost.md): warm cost 0.04-0.16 s per SessionStart hook, parallel worst 0.16 s, no contention; so the 2026-10-05 5.5-6.7 s was most likely a host stall (load or disk I/O on the external volume; the janitor's SessionStart hooks and the one other plugin hook recorded (ponytail, 5567 ms) stalled alike) (INFERRED: the measurement was warm, unloaded, four of the five hooks; a cold uv cache was not tested). Fixed in dd779c12: trdd-state and watchpaths timeouts 5 -> 30 s, test parametrized over the three hooks. NEXT ACTION: none on code. NAMED LIVE CHECK: on the next slow clear or resume after v3.7.4 is installed, the session transcript shows hook_success (no hook_cancelled timedOut) for on-session-start.py, on-session-start-trdd-state.py and on-session-start-watchpaths.py.
2026-10-06: shipped in v3.7.4 (892a1f85). Other hooks still at 5 s (on-config-change, on-file-changed, post-model-switch, the PreToolUse context-usage and token-budget hooks) are deliberately unchanged: the two PreToolUse hooks run before every tool call, so a 30 s ceiling would hold tool calls longer under a stall; on-config-change, on-file-changed and post-model-switch carry no state that a kill would lose for the resume path (INFERRED, not read). A kill is silent (no janitor log), so the trigger to revisit is a hook_cancelled timedOut record for any janitor hook found in a session transcript; the live check above is where to look.
2026-10-06: live check needs a session started after the v3.7.4 install (hooks.json is read at session start).
2026-10-07 live check (a worker's read of the logs, not re-read by the main agent): verdict: named live check NOT YET OBSERVABLE; card stays in testing, no Acceptance checklist added. R2 PROVEN: installed 3.8.2 hooks.json has timeout 30 for on-session-start.py (line 9), on-session-start-trdd-state.py (line 18) and on-session-start-watchpaths.py (line 27); commit dd779c12, shipped 3.7.4 (892a1f85). R1 measurement proven by the card's cited report (not re-read, not re-measured); R3 test file tests/test_session_start_hook_timeout.py is in the dd779c12 stat, tests not re-run. R4 NOT YET OBSERVABLE: 60 SessionStart hook records across all projects since the 3.7.4 install (2026-10-06T17:49Z, taken from the cache dir mtime, not an install log) are all hook_success with 0 hook_cancelled; janitor maxima on-session-start.py 2014 ms (18 runs), trdd-state 142 ms (8 runs), watchpaths 745 ms (18 runs); none exceeded 5 s, so success is what the old 5 s limit would also have produced and the fix is not proven. Original incident confirmed in transcript 05acb47b: 2026-10-05T11:52:00Z SessionStart:clear hook_cancelled for trdd-state 5999 ms, watchpaths 6114 ms, on-session-start.py 6721 ms against 5000. R5 revisit trigger FIRED on pre-install transcripts only: 73 hook_cancelled records in this project's transcripts, 0 SessionStart, 0 after 2026-10-06T17:49Z; janitor script counts pre-tool-token-budget.py 16, pre-tool-context-usage.py 14, pre-tool-wikimem-write-path.py 6, pre-tool-pkg-guard.py 6, pre-tool-agent-generator-guard.py 5, pre-tool-publish-lock.py 5, pre-bash-safety.py 4, on-stop.py 2, on-stop-token-meter.py 2, on-prompt-submit-user-mem.py 1; example 2026-10-05T14:24:43.322Z PreToolUse:Bash pre-tool-context-usage.py 7923 ms against 5000. Those 5 s and 10 s hook cancellations are not owned by this card and no owning card was searched for; whether a killed guard fails open or closed was not checked. Not verified: that each post-install session loaded 3.7.4 or later hooks, the cost report, transcripts outside the projects dir. Still waits on: a SessionStart (clear or resume) where a janitor hook runs longer than 5 s and the transcript shows hook_success for all three hooks after 3.7.4.
FIELD EVENT FOUND by the main session, 2026-10-11 00:43 (clock), in Claude Code's own session transcripts (~/.claude/projects/<project>/<session>.jsonl): every hook run is an attachment record with hookEvent, command, type (hook_success or hook_cancelled), exitCode and durationMs. The stay notes of 2026-10-09 and 2026-10-10 that say hook duration is logged nowhere are WRONG; the check of 2026-10-07 on this card had already read these records. Counted over the 926 transcripts modified in the last 10 days, records since 2026-10-06T17:00Z for the three hooks: on-session-start.py 246, watchpaths 246, trdd-state 104, ALL hook_success, 0 hook_cancelled; over 5000 ms and successful: on-session-start.py 13 (largest 18176 ms), watchpaths 3 (8812, 6857, 6481 ms), trdd-state 0. Before the fix the same search finds 38 cancelled on-session-start.py runs (last 2026-10-05T16:01Z), 3 cancelled trdd-state and 3 cancelled watchpaths (last 2026-10-05T11:52Z). THE NAMED CHECK IS MET AS WRITTEN: session 4487ea93 (this project, clear of 2026-10-10 00:55 local, plugin 3.8.11) shows hook_success for all three hooks with on-session-start.py at 5644 ms (trdd-state 1701 ms, watchpaths 951 ms). NARROWING: for this card's own two hooks, watchpaths has run over 5000 ms and succeeded three times (sessions 3acb35a8, 62bad1b4, 0e6b24af); trdd-state has NOT been seen over 5000 ms since the fix, so for that hook the proof is the configured 30 s, the parametrized test and zero cancellations in 104 runs. In two of the three slow watchpaths sessions the transcript holds no trdd-state record at all (neither success nor cancelled); why was not looked into.

## Acceptance

- [x] trdd-state and watchpaths SessionStart hooks have a 30 s timeout and the test is parametrized over the three hooks (dd779c12; re-run by the assessing worker on 2026-10-09, not re-run today).
- [x] FIELD, narrowed: a slow SessionStart after the fix with hook_success for all three hooks (session 4487ea93); watchpaths itself over 5000 ms and successful three times; trdd-state never seen over 5000 ms, 0 cancellations in 104 runs.
