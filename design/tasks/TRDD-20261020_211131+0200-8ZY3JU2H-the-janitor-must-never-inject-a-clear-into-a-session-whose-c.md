---
trdd-id: 8ZY3JU2H
title: The janitor must never inject a /clear into a session whose context is far below the cap
column: todo
status: tasked
created: 2026-10-20T21:11:31+0200
updated: 2026-10-20T22:12:59+0200
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

THE WINDOW IS WRONG, NOT THE FLOOR - measured, AND THE VALUE IS 480000. The environment has CLAUDE_CODE_AUTO_COMPACT_WINDOW=480000 (set globally in ~/.claude/settings.json, so every project inherits it); the live environment agrees. CORRECTION (2026-10-20 22:15): this card first recorded the value as 430000. MEASURED, the settings file and the live env both say 480000, and the string 430000 appears NOWHERE in the settings tree - the 2026-10-20 morning backups carry 800000, so the value changed during the day. 83 percent of 480000 is 398,400 - not 356,900. Every percentage-shaped floor in the codebase is computed against THAT number, not against the session's REAL 1,000,000-token window. The percentage floors are therefore even FURTHER from 240k than this card first claimed, so they cannot explain a 240k clear either. THE PATH THAT CAN: the reload-shrink paths. scripts/reload_trigger.py (line ~140) and scripts/reload_skills_trigger.py (line ~120) both call clear_trigger.spawn_shrink_chain DIRECTLY, with the floor from reload_shrink.shrink_threshold() = 350_000 in auto mode - but reload_shrink.should_shrink returns True for mode == force REGARDLESS OF CONTEXT SIZE, and these are the paths that type /clear as part of a RELOAD, so the owner may have seen a /clear plus a plugin reload and not identified the clear as the actor. THE WRONG-SESSION MEASUREMENT IS THE STRONGEST HYPOTHESIS and it is present in TWO places. (a) reload_shrink.context_tokens() reads cold_cache_compact.context_tokens_for(cold_cache_compact.newest_transcript(...)) - THE NEWEST TRANSCRIPT IN THE PROJECT, NOT THIS SESSION'S OWN. In a project with several live sessions the size measured belongs to somebody else, and the /clear is typed into THIS session's pane: a cross-session mis-measurement, not merely a wrong number. (b) dispatch.py _phase_idle_clear_nudge also measures off cold_cache_compact.newest_transcript(root) - and MEASURED, the mis-measured value is passed as context_tokens=ctx INTO should_clear_when_long_idle, so it DECIDES THE GATE, not merely the print line. The code's own comment there calls it a print line; that comment is STALE. A project whose newest transcript belongs to a SMALL session (240k) can make a large session look small.

## What the fleet logs show

WHAT THE FLEET LOGS SHOW, AND WHAT THEY DO NOT - CORRECTED (2026-10-20 22:15). This card first recorded: "The lowest ever recorded is 332196 tokens ... NOT ONE clear in the entire fleet history fired below 332k." BOTH CLAIMS ARE MEASURED WRONG. (a) The 332196 line is a DECLINE, not a fire: MEASURED verbatim, "[2026-10-15T20:16:49+0200] decline trigger=- context=332196 autoCompactEnabled=True why=idle 365s < 3600s and the next fire is still warm". (b) Clears DID fire below 332k. Sweeping external-clear.log and external-clear.log.1 for lines whose trigger= is a REAL trigger (not "-", which is the decline marker) gives these six fires: 209316 and 215861 and 218951 on 2026-09-25, and 265430 and 269336 and 270691 on 2026-09-26. The lowest, 209316, IS INSIDE the 240k band the owner reported. (c) The 316972 line the card cited as the single 150k-330k refusal is a DECLINE too, and it is not in external-clear.log at all. THE RECONCILIATION, and this is the real finding: the floor is CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_MIN_CONTEXT_TOKENS, and MEASURED across the ~/.claude settings backups, that override was 200000 on 2026-09-12 through 2026-09-26 and 300000 in every later backup. All six sub-300k fires fall inside the window when the floor was 200000, and every fire since 2026-09-27 is at or above 300000. THE CORRECTED CLAIM, which the evidence supports: NO CLEAR HAS EVER FIRED BELOW THE FLOOR IN FORCE. The floor has always bound the decision, and there is NO EVIDENCE of a path that bypasses it - the opposite of what this card first asserted. WHAT REMAINS UNEXPLAINED is therefore narrower and sharper: with the floor at 300000 since 2026-09-27 and no sub-300k fire in the whole fleet since, a clear of a 240k session cannot have come from the external-clear path with a CORRECT measurement. The surviving candidates are (i) the WRONG-SESSION measurement (the wrong-session reading feeds the GATE, so a project-mate's 240k transcript authorises a clear in a large session's pane - the mechanism the code already half-knows about, since the chain payload names this session's own transcript while the SIZE GATE still reads the project's newest), (ii) a knob that bypasses the floor - reload_shrink.should_shrink returns True for mode == force regardless of size, and that path's own size input is the wrong-session reading, so one wrong number explains it, and (iii) the owner's 240k figure being an estimate rather than a measurement. The reload-shrink paths log to reload-trigger.log and their lowest recorded spawn is 354872. THE AUDIT OF ALL NINE PATHS IS IN FLIGHT (worker report at docs_dev/clear-path-audit.md): for each path, the decision site, the floor, whether a knob bypasses it, and the LOWEST measured-token value that can trigger a clear with CLAUDE_CODE_AUTO_COMPACT_WINDOW=480000.

## The fix and its acceptance

THE FIX, once the audit names the path. Three properties every /clear path must have, and at least one of them is currently missing. (1) A FLOOR IN TOKENS, not a percentage of a window that may be the wrong one, and never a FORCE mode that ignores the size entirely. (2) THE MEASUREMENT MUST BE THIS SESSION S OWN - the codebase already has the correct reader for this (the reload-shrink path even has the WRONG one, reading the project newest transcript), so the fix is to route every path through one session-scoped reader. (3) THE FLOOR MUST BE EXCEEDED BEFORE THE TRIGGER IS CONSIDERED - where the context_high_water trigger is evaluated before the min_context floor, a session measured above 480000 fires even though the floor is 300000, which is the correct behaviour there, but the same ordering applied to a 240k session would fire it wrongly. ACCEPTANCE. Every /clear path has a test proving it refuses a 240k-token session. Each test must be MUTATION-VERIFIED: restore the buggy form and confirm the test fails ON THE RULE, not on silence - a test whose subject is refused by an earlier clause is VACUOUS. Plus a test that a multi-session project cannot clear a session because ANOTHER session's transcript was the newest. And a fleet sweep over every janitor log that asserts no clear-triggered line ever fired below the floor, so the next occurrence is caught by a test and not by the owner.
