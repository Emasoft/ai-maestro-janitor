---
trdd-id: 9438CGJZ
title: SessionStart hooks share a 5 s budget a loaded host exceeds, so the STATE injection and watchpaths hooks are killed silently
column: todo
status: tasked
created: 2026-10-06T18:33:18+0200
updated: 2026-10-06T18:33:22+0200
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
---

# SessionStart hooks share a 5 s budget a loaded host exceeds, so the STATE injection and watchpaths hooks are killed silently

On 2026-10-05 (ORCHESTRATOR /clear, transcript 05acb47b) every SessionStart hook took 5.5-6.7 s and on-session-start-trdd-state.py (5999 ms) and on-session-start-watchpaths.py (6114 ms) were killed at their 5 s timeout (hooks/hooks.json), silently: a resumed session then loses its in-progress TRDD STATE blocks. on-session-start.py got 30 s in bace60f4 (TRDD-KVUVV9D2). Measure first where the start-up time goes (uv run --script resolve, interpreter start, lib imports, contention between the 5 hooks starting in parallel) before raising more limits one by one.

## Approval log

- 2026-10-06T18:33:18+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

NEXT ACTION: measure SessionStart hook start-up cost on this host (cold and warm) per hook.
