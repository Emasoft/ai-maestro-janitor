---
trdd-id: 21ODXDDS
title: trddgrep cannot correct a wrong mandated-by value on a card
column: todo
status: tasked
created: 2026-11-19T13:07:49+0100
updated: 2026-11-19T13:07:54+0100
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
approval-datetime: 2026-11-19T13:07:49+0100
relevant-rules: [34]
---

# trddgrep cannot correct a wrong mandated-by value on a card

## Symptom
Card TRDD-6IFL3OXG was created with `mandated-by: manager` although no manager exists in that session; `trddgrep set` and `trddgrep edit` both refuse the field ("written only by the create/approve code paths"), so the wrong value is now in committed history (c4834cb9). trddgrep is an ai-maestro tool: the fix belongs in the ai-maestro repo (filing there needs explicit owner approval); this card tracks it on the janitor side.

## Done means
- [ ] A sanctioned path exists to correct mandated-by, and 6IFL3OXG is corrected through it.

Filed under PRRD G34.1 (every issue becomes a ticket or a TRDD).

## Approval log

- 2026-11-19T13:07:49+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
