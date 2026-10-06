---
trdd-id: 9438CGJZ
title: SessionStart hooks share a 5 s budget a loaded host exceeds, so the STATE injection and watchpaths hooks are killed silently
column: testing
status: tasked
created: 2026-10-06T18:33:18+0200
updated: 2026-10-06T19:05:53+0200
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

## STATE

NEXT ACTION: measure SessionStart hook start-up cost on this host (cold and warm) per hook.
2026-10-06: measured (reports/continuity-build/20261006_185535+0200-sessionstart-hook-cost.md): warm cost 0.04-0.16 s per SessionStart hook, parallel worst 0.16 s, no contention; so the 2026-10-05 5.5-6.7 s was most likely a host stall (load or disk I/O on the external volume; the janitor's SessionStart hooks and the one other plugin hook recorded (ponytail, 5567 ms) stalled alike) (INFERRED: the measurement was warm, unloaded, four of the five hooks; a cold uv cache was not tested). Fixed in dd779c12: trdd-state and watchpaths timeouts 5 -> 30 s, test parametrized over the three hooks. NEXT ACTION: none on code. NAMED LIVE CHECK: on the next slow clear or resume after v3.7.4 is installed, the session transcript shows hook_success (no hook_cancelled timedOut) for on-session-start.py, on-session-start-trdd-state.py and on-session-start-watchpaths.py.
2026-10-06: shipped in v3.7.4 (892a1f85). Other hooks still at 5 s (on-config-change, on-file-changed, post-model-switch, the PreToolUse context-usage and token-budget hooks) are deliberately unchanged: the two PreToolUse hooks run before every tool call, so a 30 s ceiling would hold tool calls longer under a stall; on-config-change, on-file-changed and post-model-switch carry no state that a kill would lose for the resume path (INFERRED, not read). A kill is silent (no janitor log), so the trigger to revisit is a hook_cancelled timedOut record for any janitor hook found in a session transcript; the live check above is where to look.
