---
trdd-id: 7IPJA0ED
title: C47 — ponytail hook timeout issue
column: human_review
status: tasked
created: 2026-10-01T19:45:27+0200
updated: 2026-10-10T12:06:06+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:27+0200
---

# C47 — ponytail hook timeout issue

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C47, wave Later.

Writes (exclusive): none (issue on the ponytail plugin's repo; owner from U6)
Task: Issue on the ponytail plugin's repo about its 5 s hook timeout. The owner comes from U6.
Verify: to be set when scheduled
Depends on: none
Conflict rule: this card may write ONLY the files listed under Writes.
Outward-facing: requires USER approval before posting.

## Approval log

- 2026-10-01T19:45:27+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-10 12:06 BOARD DRAIN, wave 6 card 3, no code: this card's whole task is an issue on another plugin's repository and its body says 'Outward-facing: requires USER approval before posting'; the standing rule also forbids posting on a repository the owner's GitHub user does not own unless the owner says so. It is therefore the owner's. One possibly related observation, NOT attributed: at 2026-10-10 03:10 a HOOK-001 line reported a UserPromptSubmit hook killed at 6507 ms of a 5000 ms limit; which plugin's hook it was is not recorded. Before posting, someone must (1) name the hook and its plugin from the hook log, (2) confirm the 5 s figure in that plugin's hooks file, (3) confirm who owns its repository. No draft is written here because none of the three is known.
- 2026-10-10T12:06:06+0200 — column → human_review. outward-facing issue on another repository; the card itself requires the owner's approval
