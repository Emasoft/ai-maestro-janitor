---
trdd-id: D845AWBC
title: Index-reader inventory and migration
column: blocked
status: tasked
created: 2026-10-23T17:57:01+0200
updated: 2026-10-24T03:19:29+0200
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
npt: [UP6VP41N]
relevant-rules: [13, 14, 18]
spec: wikimem-layout-spec.md 0.2.8
blocked-by: [UXIL77GB]
pre-block-column: backburner
blocker-probe: trddgrep --porcelain show UXIL77GB
blocker-holds-if: match:\t(backburner|approval|design|design_ai_review|design_human_review|todo|verify_assumptions|plan|dispatch|dev|testing|ai_review|human_review|blocked|failed|proposal|planned)\t
blocker-probe-canary: match:UXIL77GB
---

# Index-reader inventory and migration

Spec: design/specs/wikimem-layout-spec.md 0.2.8 (draft). Implements WL-10 with VERIFY-11: list every reader of the old index (memgrep reindex and lint, janitor health checks, USER mirror sync in memory_scopes.py), move the index, keep the USER mirror from copying wm_*_index.db or its journal files, remove the old index. A scope-root move is a major change under WM-VER-01. Anchors: memory_scopes.py:582-640, index.rs:33-35. Done when: no reader refers to the old path, the mirror skips the new files, and the old index is removed.

## Approval log

- 2026-10-23T17:57:01+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-23T18:03:43+0200 — column → blocked. waits on UXIL77GB
- 2026-10-24T03:19:28+0200 — VERIFY-11 measured (spec F23): today's _MIRROR_IGNORE (memory_scopes.py:481) skips only .memgrep, so wm_*_index.db and its journals placed beside the pages WOULD be mirrored; this card must extend the filter and remove the old index. Other copy/move/delete paths were not enumerated; list them here before the move.
