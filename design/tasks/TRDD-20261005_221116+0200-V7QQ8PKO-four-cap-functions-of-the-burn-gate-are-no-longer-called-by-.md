---
trdd-id: V7QQ8PKO
title: Four cap functions of the burn gate are no longer called by production code
column: todo
status: tasked
created: 2026-10-05T22:11:16+0200
updated: 2026-10-05T22:11:16+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:16+0200
---

# Four cap functions of the burn gate are no longer called by production code

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

observe_wall, record_cap_sample, store_caps and the learned-cap arm of live_burn_verdict are reached only by tests since TRDD-YVC3F06V. Decide: keep for TRDD-AWIWXJIG with a note in the code, or delete.

## Approval log

- 2026-10-05T22:11:16+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
