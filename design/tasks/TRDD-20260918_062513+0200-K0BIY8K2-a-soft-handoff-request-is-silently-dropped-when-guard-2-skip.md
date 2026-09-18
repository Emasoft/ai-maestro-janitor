---
trdd-id: K0BIY8K2
title: A soft handoff request is silently dropped when guard 2 skips the compact
column: backburner
created: 2026-09-18T06:25:13+0200
updated: 2026-09-18T06:25:13+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: bugfix
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-18T06:25:13+0200
---

# A soft handoff request is silently dropped when guard 2 skips the compact

compact_trigger.py guard 2 returns before send_self_command, so with --handoff (soft) neither /janitor-write-handoff nor /compact is sent; the user asked for a handoff, which is not written. Question for the user: should the handoff still be sent when only the compact is skipped.

## Approval log

- 2026-09-18T06:25:13+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
