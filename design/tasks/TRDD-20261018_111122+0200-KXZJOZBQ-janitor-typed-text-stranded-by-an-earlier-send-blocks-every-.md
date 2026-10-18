---
trdd-id: KXZJOZBQ
title: Janitor-typed text stranded by an earlier send blocks every later injection
column: todo
status: tasked
created: 2026-10-18T11:11:22+0200
updated: 2026-10-18T11:11:22+0200
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
approval-datetime: 2026-10-18T11:11:22+0200
---

# Janitor-typed text stranded by an earlier send blocks every later injection

Split from TRDD-S8BZI761 (review of its round-2 plan, 2026-10-18). S8BZI761's fix clears a wrapped field only inside the send that typed it. Text already stranded before a send (a crash, a give-up mid-clear, the released version) stays: on 2026-10-13 the next sends were /clear, which only waited on field not empty for hours. A fix must recognise text the janitor itself typed recently (the user_intent machine-typed crumb, TTL 2 h, looked up by ANY recent machine-typed command, not the current one) at the start of a send, and clear it with the same suffix-of-our-own-text rule, never touching user text. TO DO FIRST: read user_intent.note_machine_typed and its readers, and how inject_until_sent's rule 1 (field not empty) could consult them.

## Approval log

- 2026-10-18T11:11:22+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
