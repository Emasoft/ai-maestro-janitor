---
trdd-id: R9NLNV3W
title: janitor liveness mod for own-session structured transcript reading
column: backburner
status: tasked
created: 2026-11-11T18:40:16+0100
updated: 2026-11-13T17:39:26+0100
current-owner: user
created-by: user
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: user
mandate: true
mandated-by: none
approved: true
approval-judge: user
approval-datetime: 2026-11-11T18:40:16+0100
---

# janitor liveness mod for own-session structured transcript reading

## Approval log

- 2026-11-11T18:40:16+0100 — MANDATE issued by user (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

CURRENT (2026-11-13, mods-expert-developer) — hooks/liveness/{logic.ts,register.ts,tests/liveness.test.ts} written, uncommitted, UNWIRED (hooks/hooks.json has no modules key; decision and measurements under Notes). Design as built: structural signals only (session.append door notice + name api_error per retry attempt, turn.start/turn.complete with reason, session.end with e.sessionId; subagent events ignored; the engine's '<synthetic>' API Error reply is not progress), one report per session at .janitor/state/mod-liveness/<session-id>.json, kinds idle/working/api_retry/api_error/ended, alive_at stamped every 30 s tick. Superseded: the $.session.messages() tail/regex design, the retry_wedge kind and the $.command.run probe (the mod makes no recovery call). check-mod.sh == PASS (15 tests), 10/10 mutations red; live checks on 2.1.323 recorded under Notes. Column left at backburner for the orchestrator. NEXT: a daemon reader card (prune old files; check the process before treating a stale alive_at as a frozen loop) and the TRDD-2V7OAUPE single-entry-module decision. Owner directive kept: ONLY the mods-expert-developer agent may develop or review mods-related work.

## Notes

2026-11-13 decision (mods-expert-developer): option (a), hooks/hooks.json stays UNWIRED; the liveness module ships unwired and is live-tested only from a scratch plugin shell. Measured: claude 2.1.323 plugin validate refuses a second modules entry ('hooks.json modules names one hooks module per plugin; a second entry is refused'), so wiring liveness would take the one slot TRDD-2V7OAUPE needs for the secret-shield, and sharing it (one entry module registering both) is that card's design call; plugin validate of 2.1.200 and 2.1.250 (isolated CLAUDE_CONFIG_DIR): 2.1.200 does not validate hooks.json at all, so it cannot pass or refuse a modules key; 2.1.250 does validate it and passes a hooks.json with a modules key, but runtime loading on a pre-2.1.287 Claude Code stays unmeasured (TRDD-TEP6F3A3); nothing reads the state file yet. Option (b) rejected: narrowing tests/test_secret_shield_wiring_gate.py would open the gate for a module that blocks the shield's slot. The modules line was removed (git diff --quiet -- hooks/hooks.json exits 0).
2026-11-13 live measurements (2.1.323, dead ANTHROPIC_BASE_URL in a scratch repo): each retry attempt reaches session.append as door notice, message.type system, name api_error, origin engine, EMPTY content (attempt/retryInMs only in the transcript row with the same uuid); $.session.messages() never returns these rows (user/assistant only), so the earlier text-regex design could not see a retry; clock.every ticks kept firing through the retry backoff; ESC ends the turn as turn.complete reason aborted and puts the interrupted prompt back in the composer, so typing resume produced 'say hiresume' (relevant to TRDD-RJJGXPIK recovery). Implementation now at hooks/liveness/{logic.ts,register.ts,tests/liveness.test.ts}, one report per session at .janitor/state/mod-liveness/<session-id>.json; derived: the future reader/wiring card must prune old per-session files ($.fs has no delete).
2026-11-13 more live measurements (2.1.323): (1) a turn that runs out of retries (fixture server: 529 then 400) appends notice api_error, THEN a door response row from origin model '<synthetic>' with text 'API Error: 400 ...', THEN turn.complete reason error; the synthetic row is now excluded from progress so the retry run survives to the api_error report (test + mutation added). CLAUDE_CODE_MAX_RETRIES=2 was ignored (screen showed attempt 10/100). (2) /reload-plugins with the module unchanged fired no new session.start and the single heartbeat kept a 30 s spacing; a save-triggered hot reload re-ran session.start (since reset) and afterwards writes stayed one per ~30 s (intervals 30.5, 30.4, 30.0 s), so no duplicate timer was observed.
2026-11-13: derived follow-ups: TRDD-I6FUQ4SD (daemon reader + pruning), TRDD-KADV0ZO6 (publish gate now also runs the liveness tests).
