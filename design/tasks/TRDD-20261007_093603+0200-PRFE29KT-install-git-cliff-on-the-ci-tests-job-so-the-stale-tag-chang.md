---
trdd-id: PRFE29KT
title: Install git-cliff on the CI Tests job so the stale-tag changelog tests run there
column: todo
status: tasked
created: 2026-10-07T09:36:03+0200
updated: 2026-10-07T09:36:03+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T09:36:03+0200
---

# Install git-cliff on the CI Tests job so the stale-tag changelog tests run there

556b78be skips two tests (the TNNII9S8 stale-tag changelog tests) where git-cliff is absent. Add an install step for git-cliff to the CI Tests job, pinned per the workflow rules (an action pinned to a commit SHA, or a pinned release), so those tests run on the runner again.

## Approval log

- 2026-10-07T09:36:03+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
