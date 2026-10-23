---
trdd-id: D845AWBC
title: Index-reader inventory and migration
column: backburner
status: tasked
created: 2026-10-23T17:57:01+0200
updated: 2026-10-23T17:57:02+0200
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
approval-datetime: 2026-10-23T17:57:01+0200
npt: [UP6VP41N, UXIL77GB]
relevant-rules: [13, 14, 18]
spec: wikimem-layout-spec.md 0.2.3
---

# Index-reader inventory and migration

Spec: design/specs/wikimem-layout-spec.md 0.2.3 (draft). Implements WL-10 with VERIFY-11: list every reader of the old index (memgrep reindex and lint, janitor health checks, USER mirror sync in memory_scopes.py), move the index, keep the USER mirror from copying wm_*_index.db or its journal files, remove the old index. A scope-root move is a major change under WM-VER-01. Anchors: memory_scopes.py:582-640, index.rs:33-35. Done when: no reader refers to the old path, the mirror skips the new files, and the old index is removed.

## Approval log

- 2026-10-23T17:57:01+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
