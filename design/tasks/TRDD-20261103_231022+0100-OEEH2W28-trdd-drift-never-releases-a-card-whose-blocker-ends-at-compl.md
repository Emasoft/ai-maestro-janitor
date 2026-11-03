---
trdd-id: OEEH2W28
title: trdd-drift never releases a card whose blocker ends at completed and calls a never-shipped blocker cleared
column: design
status: tasked
created: 2026-11-03T23:10:22+0100
updated: 2026-11-03T23:10:22+0100
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
approval-datetime: 2026-11-03T23:10:22+0100
---

# trdd-drift never releases a card whose blocker ends at completed and calls a never-shipped blocker cleared

## Problem

- scripts/lib/trdd_common.py TERMINAL_COLUMNS (line 451) lacks "completed", while DONE_COLUMNS (line 469) has it, and norm_state does not map completed to complete. Measured: is_terminal_column("completed") is False, is_done_column("completed") is True. So a blocked card whose unblock-when is trdd:<id> terminal and whose blocker ends at completed is never restored by trdd-drift _try_unblock, though the blocker shipped.
- Check 4 stale blockers (trdd_common.py around line 1223) uses BLOCKER_CLEARED_COLUMNS = TERMINAL_COLUMNS, so it reports a failed, cancelled, superseded or refused blocker as cleared. An agent acting on that report and emptying blocked-by would let a terminal predicate alone release the card, bypassing the DONE_COLUMNS hold in _try_unblock.

## Found during

- Found during TRDD-M1218EMH while wiring TRDD-2V7OAUPE; the hold is pinned by test_try_unblock_holds_when_blocked_by_is_terminal_but_not_done (tests/test_trdd_drift_unblock_when.py, commit 842a8835).

## Approval log

- 2026-11-03T23:10:22+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
