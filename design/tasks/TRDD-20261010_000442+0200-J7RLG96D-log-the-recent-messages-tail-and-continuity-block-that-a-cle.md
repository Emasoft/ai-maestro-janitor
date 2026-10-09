---
trdd-id: J7RLG96D
title: Log the recent-messages tail and continuity block that a clear handoff injects
column: todo
status: tasked
created: 2026-10-10T00:04:42+0200
updated: 2026-10-10T00:04:42+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T00:04:42+0200
---

# Log the recent-messages tail and continuity block that a clear handoff injects

Two testing cards wait on something nothing records. TRDD-DS3WDTPV needs a janitor clear whose last reply ended on a question, followed by a turn that makes a work tool call; TRDD-IYNS7H83 needs a clear handoff taken after 20 or more consecutive heartbeat fires that still shows the last substantive assistant message. The text the SessionStart hook injects after a clear (the Continuity block, the NEXT ACTION sentence, the recent-messages tail) is not written to any log, so today the only observer is the resumed session itself, and a later session cannot re-check it. Wanted: on the post-clear path, write the injected continuity text and recent-messages tail to a file under .janitor/logs/ or .janitor/state/ keyed by the new session id, bounded in size, with no secret-bearing content beyond what the handoff already holds. Done when both cards' checks can be made by reading that file.

## Approval log

- 2026-10-10T00:04:42+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
