---
trdd-id: 8ZY3JU2H
title: The janitor must never inject a /clear into a session whose context is far below the cap
column: todo
status: tasked
created: 2026-10-20T21:11:31+0200
updated: 2026-10-20T21:13:09+0200
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
approval-datetime: 2026-10-20T21:11:31+0200
relevant-rules: [12.1]
---

# The janitor must never inject a /clear into a session whose context is far below the cap

## Approval log

- 2026-10-20T21:11:31+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## The report

2026-10-20 21:10 - OWNER REPORT (verbatim): the janitor injected /clear even in agents with only 240k of context. The owner then clarified the figure: 240,000 tokens used of a 1,000,000-token window - i.e. 24% occupancy. A /clear at 24% occupancy destroys a working conversation for no token saving whatsoever.

## What the code says - the floors that exist

2026-10-20 21:15 - MEASURED against the code. There is no single /clear path: there are at least NINE, each with its OWN floor, trigger and knobs. The bug is almost certainly ONE of them missing a floor, or a floor compared against the WRONG window.

## The three floors that exist

THE THREE FLOORS THAT EXIST. (1) scripts/lib/cold_cache_compact.py - the idle-clear path (dispatch.py _phase_idle_clear_nudge, line 3432). Floor DEFAULT_CLEAR_MIN_CONTEXT_TOKENS = 300_000, checked in should_clear_when_long_idle: context_tokens is None or < min_context_tokens => refuse. A 240k context is REFUSED here. (2) scripts/lib/external_clear.py - the external/abandoned-session path (external_handoff_clear.py). Floor DEFAULT_MIN_CONTEXT_TOKENS = 300_000 in _should_clear_externally_decide: context_tokens is None or < min_context => refuse. A 240k context is REFUSED here too - BUT THE ORDERING IS THE SUSPECT: the context_high_water trigger (TRIGGER_CONTEXT_PRESSURE) is evaluated BEFORE the min_context floor, and context_high_water_tokens() resolves to CLAUDE_CODE_AUTO_COMPACT_WINDOW. (3) scripts/hooks/on-stop-token-meter.py - the turn-boundary path. Its floor is a PERCENTAGE: _DEFAULT_CLEAR_AT_PCT = 83 of the resolved window, via _pct_tokens (capped at window minus 34_000 summary overhead).

## The wrong window, and the wrong session

THE WINDOW IS WRONG, NOT THE FLOOR - measured. The environment has CLAUDE_CODE_AUTO_COMPACT_WINDOW=430000 (set globally in ~/.claude/settings.json, so every project inherits it). Every percentage-shaped floor in the codebase is computed against THAT number, not against the session's REAL 1,000,000-token window. 83 percent of 430000 is 356,900 tokens - still above 240k, so the percentage floors cannot explain a 240k clear either. THE PATH THAT CAN: the reload-shrink paths. scripts/reload_trigger.py (line ~140) and scripts/reload_skills_trigger.py (line ~120) both call clear_trigger.spawn_shrink_chain DIRECTLY, with the floor from reload_shrink.shrink_threshold() = 350_000 in auto mode - but reload_shrink.should_shrink returns True for mode == force REGARDLESS OF CONTEXT SIZE, and these are the paths that type /clear as part of a RELOAD, so the owner may have seen a /clear plus a plugin reload and not identified the clear as the actor. THE WRONG-SESSION MEASUREMENT IS THE STRONGEST HYPOTHESIS and it is present in TWO places. (a) reload_shrink.context_tokens() reads cold_cache_compact.context_tokens_for(cold_cache_compact.newest_transcript(...)) - THE NEWEST TRANSCRIPT IN THE PROJECT, NOT THIS SESSION'S OWN. In a project with several live sessions the size measured belongs to somebody else, and the /clear is typed into THIS session's pane: a cross-session mis-measurement, not merely a wrong number. (b) dispatch.py _phase_idle_clear_nudge also measures off cold_cache_compact.newest_transcript(root) for its print line, and its own code comment concedes the chain payload then names THIS session. A project whose newest transcript belongs to a SMALL session (240k) can make a large session look small.

## What the fleet logs show

WHAT THE FLEET LOGS SHOW, AND WHAT THEY DO NOT. Every clear-trigger.log line on this machine was swept for the lowest token count that ever fired a clear. The lowest ever recorded is 332196 tokens (33 percent of window, EMASOFT-INTEGRATOR-AGENT, 2026-10-01), then 351616 (35 percent), 353420 (35 percent), 359344 (35 percent), 381998 (38 percent). NOT ONE clear in the entire fleet history fired below 332k. The reload-shrink paths log to reload-trigger.log and their lowest recorded spawn is 354872. So a 240k clear is NOT the normal shape of any logged path: it is either a path that does not log, a path whose floor is bypassed by a knob, or a measurement that read the WRONG SESSION. A fleet-wide sweep also found exactly ONE clear-related log line in the 150k-330k band, and it was a REFUSAL: EMASOFT-INTEGRATOR-AGENT 2026-09-29, decline trigger=- context=316972 autoCompactEnabled=True why=cache state unknown -- not clearing. THE AUDIT OF ALL NINE PATHS IS IN FLIGHT (worker report at docs_dev/clear-path-audit.md): for each path, the decision site, the floor, whether a knob bypasses it, and the LOWEST measured-token value that can trigger a clear with CLAUDE_CODE_AUTO_COMPACT_WINDOW=430000.

## The fix and its acceptance

THE FIX, once the audit names the path. Three properties every /clear path must have, and at least one of them is currently missing. (1) A FLOOR IN TOKENS, not a percentage of a window that may be the wrong one, and never a FORCE mode that ignores the size entirely. (2) THE MEASUREMENT MUST BE THIS SESSION S OWN - the codebase already has the correct reader for this (the reload-shrink path even has the WRONG one, reading the project newest transcript), so the fix is to route every path through one session-scoped reader. (3) THE FLOOR MUST BE EXCEEDED BEFORE THE TRIGGER IS CONSIDERED - where the context_high_water trigger is evaluated before the min_context floor, a session measured above 430000 fires even though the floor is 300000, which is the correct behaviour there, but the same ordering applied to a 240k session would fire it wrongly. ACCEPTANCE. Every /clear path has a test proving it refuses a 240k-token session. Each test must be MUTATION-VERIFIED: restore the buggy form and confirm the test fails ON THE RULE, not on silence - a test whose subject is refused by an earlier clause is VACUOUS. Plus a test that a multi-session project cannot clear a session because ANOTHER session's transcript was the newest. And a fleet sweep over every janitor log that asserts no clear-triggered line ever fired below the floor, so the next occurrence is caught by a test and not by the owner.
