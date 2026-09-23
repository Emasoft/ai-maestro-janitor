---
trdd-id: 0UQSAFCW
title: The recent-turns tail injected after a clear is full of heartbeat and notification records
column: testing
created: 2026-09-23T20:17:58+0200
updated: 2026-09-23T23:23:38+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-23T20:17:58+0200
derived: true
parent-trdd: RAEGS1D5
---

# The recent-turns tail injected after a clear is full of heartbeat and notification records

Card 2a of the Jev reference gap analysis (2026-09-23, reports/compaction-replacement/20260923_200805+0200-jev-reference-gap-analysis.md §2.1). external_clear.recent_messages (external_clear.py, used by on-session-start-post-clear-compact.py and summarize_previous_session.py) feeds the recent-turns tail of the INJECTED copy and filters nothing: no isMeta, no heartbeat, no task-notification, no sidechain; it also reads the whole file with no tail seek. In a heartbeat-driven session its 12 lines are heartbeat prompts, heartbeat replies and notifications. Fix: use the stdlib classifier scripts/lib/transcript_roles.py (card 1, TRDD-RAEGS1D5) to skip sidechain, meta, system and notification prompts and bare heartbeat replies; read from the tail. Test: a heartbeat-dominated fixture yields the human turns and their replies. Acceptance: the tail of a recent real transcript contains the last human message. Depends on card 1 landing. Blocks the Jev publish.

## Approval log

- 2026-09-23T20:17:58+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-23T21:10:49+0200 — column → testing. code landed and committed 2026-09-23 with tests; awaiting the real-transcript compaction on the final tree and the release
