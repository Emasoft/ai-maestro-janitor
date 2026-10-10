---
trdd-id: 157ECFYK
title: A worker's inference was relayed to the owner as a fact and had to be withdrawn
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

# A worker's inference was relayed to the owner as a fact and had to be withdrawn

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

On 2026-10-05 the main session told the owner that a token 'was renewed', from a worker's report whose own author marked that section as inferred. Add to worker prompts and to the relay step that an inferred section is quoted as inferred.

## Approval log

- 2026-10-05T22:11:21+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T19:19:49+0200 — COMPLETE by main-agent@ai-maestro-janitor. the rule asked for exists in the owner's standing rules; no place in this repository to add it.

## Acceptance

- [x] Narrowed, decided on 2026-10-10 19:19, nothing built in this repository. The rule the card asks for exists in the owner's standing rules, which every session and worker loads: verification-and-evidence.md, section 'A sub-agent's report is evidence to check, not a decision to accept', with the markers VERIFIED, INFERRED and UNCERTAIN (file last changed 2026-10-05 21:03; both phrases counted in it today). The janitor ships no worker prompt of its own for main-session delegations, so there is no place in this repository to add the sentence; the briefs of this board drain carry it per worker ('Mark every claim as VERIFIED or INFERRED'). NOT DONE and not possible here: a mechanical guard that stops an inferred sentence from being relayed as fact. The rule was in force in some form when the event happened, so it lowers the odds and does not prevent a repeat.
