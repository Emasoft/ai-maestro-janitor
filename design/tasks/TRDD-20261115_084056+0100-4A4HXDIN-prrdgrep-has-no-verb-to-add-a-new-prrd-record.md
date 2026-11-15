---
trdd-id: 4A4HXDIN
title: prrdgrep has no verb to add a new PRRD record
column: todo
status: tasked
created: 2026-11-15T08:40:56+0100
updated: 2026-11-15T08:40:56+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-15T08:40:56+0100
---

# prrdgrep has no verb to add a new PRRD record

prrdgrep (G12.1 makes it the only PRRD write path) can only replace text on an existing line. Adding the owner-authorized silver rule S27.1 (TRDD-FADYLSQB) failed on 2026-11-15: appending to another record's line is refused by the version gate (rule S6.1's TEXT changed but its version did not), and --expect-blank only deletes a blank line. Its help says a missing verb is filed as a TRDD, not worked around. Needed: a verb that inserts a new record, with its blank separator, at the end of a named section, under the same lock, staleness guard and field gate. Then add S27.1 exactly as recorded on TRDD-FADYLSQB.

## Approval log

- 2026-11-15T08:40:56+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
