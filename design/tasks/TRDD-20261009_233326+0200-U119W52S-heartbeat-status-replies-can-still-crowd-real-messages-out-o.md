---
trdd-id: U119W52S
title: Heartbeat status replies can still crowd real messages out of the Jev newest-messages block and the pre-compact tail
column: todo
status: tasked
created: 2026-10-09T23:33:26+0200
updated: 2026-10-09T23:33:26+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-09T23:33:26+0200
---

# Heartbeat status replies can still crowd real messages out of the Jev newest-messages block and the pre-compact tail

Sibling of TRDD-IYNS7H83, found by its adversarial review on 2026-10-09 and NOT yet verified by reading the two functions. IYNS7H83 caps runs of short 'janitor heartbeat plus status line' replies in external_clear.recent_messages only. Two other views keep such replies and are bounded by count or bytes: the 'Newest messages since the last compaction' block in scripts/lib/jev_compaction.py (a contiguous run backward from the newest message under a byte budget) and the tail built in scripts/hooks/pre-compact-handoff.py (around line 482, which filters with is_heartbeat_reply only). First step: read both functions and build a failing test with one substantive assistant message followed by 20 status replies; if either view loses the substantive message, apply the same run cap through transcript_roles.is_heartbeat_status_reply so all callers agree. Known bound that no line cap removes: recent_messages reads the last 512 KiB of the transcript, so after roughly 30 or more fires the substantive message is outside the window entirely.

## Approval log

- 2026-10-09T23:33:26+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
