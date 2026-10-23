---
trdd-id: 2H2TV5ZT
title: Version the USER memory root with local git
column: backburner
status: tasked
created: 2026-10-23T17:57:05+0200
updated: 2026-10-23T18:08:13+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-23T17:57:05+0200
npt: [L25PQ3HJ]
relevant-rules: [13, 14, 19]
spec: wikimem-layout-spec.md 0.2.8
---

# Version the USER memory root with local git

Spec: design/specs/wikimem-layout-spec.md 0.2.8 (draft). Implements WL-19. The USER root becomes a local, never-pushed git repository; memgrep commits after every write batch that touched USER pages, inside the write lock; revert is git revert; the mirror sync stays as a second copy. Anchor: memory_scopes.py:582-640. Done when: every USER write batch is a commit and a revert restores a page.

## Approval log

- 2026-10-23T17:57:05+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
