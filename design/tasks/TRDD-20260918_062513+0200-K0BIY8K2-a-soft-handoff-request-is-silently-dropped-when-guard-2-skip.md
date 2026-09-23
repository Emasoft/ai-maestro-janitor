---
trdd-id: K0BIY8K2
title: A soft handoff request is silently dropped when guard 2 skips the compact
column: backburner
created: 2026-09-18T06:25:13+0200
updated: 2026-09-18T06:36:24+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-18T06:25:13+0200
---

# A soft handoff request is silently dropped when guard 2 skips the compact

compact_trigger.py guard 2 returns before send_self_command, so with --handoff (soft) neither /janitor-write-handoff nor /compact is sent; the user asked for a handoff, which is not written. Question for the user: should the handoff still be sent when only the compact is skipped.

## Approval log

- 2026-09-18T06:25:13+0200 — MANDATE issued by Emasoft (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-18T06:36:21+0200 — correction: minted by a janitor-main-session worker under the user's general go-ahead, not a mandate for this specific card; the 06:25:13 MANDATE line was the tool's default attribution.
