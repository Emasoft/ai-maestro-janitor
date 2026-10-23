---
trdd-id: UP6VP41N
title: Inventory every reader of the memgrep index file
column: backburner
status: tasked
created: 2026-10-23T17:56:19+0200
updated: 2026-10-23T17:56:20+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-23T17:56:19+0200
relevant-rules: [13, 14, 18]
spec: wikimem-layout-spec.md 0.2.3
---

# Inventory every reader of the memgrep index file

Spec: design/specs/wikimem-layout-spec.md 0.2.3 (draft). VERIFY-11 restated: List every reader of root/.memgrep/index.db: memgrep reindex and lint, janitor health checks, and the USER mirror sync in memory_scopes.py. The mirror must not copy wm_*_index.db or its journal files; the old index must be removed after the move. Blocks: WL-10 and the index migration card. Done when: the measurement is recorded as a fact in the spec's WL-FACT section with its evidence.

## Approval log

- 2026-10-23T17:56:19+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
