---
trdd-id: 3OCFOXD2
title: The main session printed two long transcript dumps into its own context
column: complete
status: archived
created: 2026-10-05T22:11:21+0200
updated: 2026-10-10T19:19:49+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:21+0200
---

# The main session printed two long transcript dumps into its own context

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Two searches on 2026-10-05 printed about 120 and about 80 long rows and the token-spike hook fired. Such searches belong in a worker or must write to a file and print a count.

## Approval log

- 2026-10-05T22:11:21+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T19:19:49+0200 — COMPLETE by main-agent@ai-maestro-janitor. rule and reporting guard both exist; no code by decision.

## Acceptance

- [x] Narrowed, decided on 2026-10-10 19:19, nothing built. Both halves of the card's remedy already exist: the owner's standing instructions say to capture large output to a file and inspect the file (CLAUDE.md, 'Files and edits'), and the janitor's own guard, scripts/hooks/pre-tool-token-budget.py, is the hook that fired on the two dumps. So the event was a rule not followed and a guard that reported it afterwards. NOT DONE: making that hook refuse the call instead of reporting it; it was not read here, and blocking a search on a size it can only know after the fact is a design of its own.
