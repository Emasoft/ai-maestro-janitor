---
trdd-id: 8BNV75TV
title: trdd-state-reconciliation flags testing cards that are correctly waiting on a live event
column: backburner
status: tasked
created: 2026-10-07T00:45:39+0200
updated: 2026-10-07T00:45:39+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T00:45:39+0200
---

# trdd-state-reconciliation flags testing cards that are correctly waiting on a live event

The detector's closeable-candidate class means only that a commit citing the card is in a released tag. On 2026-10-07 a triage of 32 such candidates found 1 closeable, 16 waiting on a live event that cannot be forced, 7 open and 8 owner decisions (the 2026-10-07 triage report). GitHub #332 therefore re-surfaces the same cards every week.

Proposed fix, tests first: skip a testing card whose STATE names a pending live event and records a field check within the last N days; keep flagging cards with no recent field check.

## Approval log

- 2026-10-07T00:45:39+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
