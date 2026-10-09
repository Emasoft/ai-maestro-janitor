---
trdd-id: 6XNWQZEG
title: Log how long each SessionStart hook ran so a slow but successful start can be seen
column: todo
status: tasked
created: 2026-10-10T00:04:41+0200
updated: 2026-10-10T00:04:41+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T00:04:41+0200
---

# Log how long each SessionStart hook ran so a slow but successful start can be seen

Two testing cards, TRDD-KVUVV9D2 and TRDD-9438CGJZ, raised the SessionStart hook timeouts from 5 s to 30 s. Their field check is a SessionStart where a hook ran longer than 5000 ms and still succeeded. Nothing records how long a SessionStart hook ran: .janitor/logs/session-start.log has an 'entered' line and no duration, so every clear seen since the fix is only a proxy and neither card can close on its named event. Wanted: one line per SessionStart hook run with its elapsed milliseconds (on-session-start.py, the trdd-state hook and the watchpaths hook), written at exit. Done when a grep of that log for a duration over 5000 with a normal exit is possible. Not verified: whether Claude Code's own transcript already records hook durations in a field that could be read instead; check that first.

## Approval log

- 2026-10-10T00:04:41+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
