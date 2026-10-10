---
trdd-id: FU8MZ0SL
title: Identical heartbeat replies that carry a prose drift line are never capped in any transcript view
column: todo
status: tasked
created: 2026-10-10T02:42:48+0200
updated: 2026-10-10T02:42:48+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T02:42:48+0200
---

# Identical heartbeat replies that carry a prose drift line are never capped in any transcript view

Found by the adversarial review of 8d1b205e (TRDD-U119W52S) on 2026-10-10 and then measured by the main session. The status-run cap covers only replies whose every line after the heartbeat phrase is a dispatcher line. A reply such as the heartbeat phrase followed by a rotator alert line is prose to that rule, so it is never capped in external_clear.recent_messages, the pre-compact tail or the Jev injected block, and a usage-limit stall, the longest quiet stretch a session has, produces exactly such replies every fire. MEASURED on the 40 newest transcripts of this project (script kept in the session scratchpad, not in the repo): runs of 3 or more consecutive IDENTICAL non-status heartbeat replies occurred 7 times (lengths 3, 3, 4, 5, 6, 8, 10); runs of 3 or more non-status heartbeat replies of any text, with no other assistant message between, occurred 37 times, the longest 17, but most of those carry real work notes and must not be capped. Proposed first step: a failing test per view with one real message followed by 10 identical drift replies; then extend the cap so a reply whose text equals the newer reply in the same run counts toward the run, through transcript_roles so all three views agree. An identical-text rule was rejected for STATUS replies in TRDD-IYNS7H83 because 10 of 14 real status replies differed in text; that measurement does not apply here, where the texts are identical by construction. Not measured: how often such a run precedes a real compaction or clear.

## Approval log

- 2026-10-10T02:42:48+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
