---
trdd-id: Q9OVLEAQ
title: trddgrep warns that the PRRD carries no project-id field each time a card is created
column: todo
status: tasked
created: 2026-10-05T22:08:49+0200
updated: 2026-10-05T22:08:49+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:49+0200
---

# trddgrep warns that the PRRD carries no project-id field each time a card is created

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed on trddgrep new: 'no project-id: <repo>/design/requirements/PRRD.md carries no project-id field'. The card is still created. To do: decide whether this repository's PRRD should carry the field (the TRDD rule says a project-scope card SHOULD carry project-id) and add it through prrdgrep, or record why not.

## Approval log

- 2026-10-05T22:08:49+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
