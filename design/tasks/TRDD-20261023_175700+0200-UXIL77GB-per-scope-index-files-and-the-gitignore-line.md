---
trdd-id: UXIL77GB
title: Per-scope index files and the gitignore line
column: backburner
status: tasked
created: 2026-10-23T17:57:00+0200
updated: 2026-10-24T03:20:11+0200
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
approval-datetime: 2026-10-23T17:57:00+0200
relevant-rules: [13, 14, 17, 18]
spec: wikimem-layout-spec.md 0.2.8
npt: []
blocked-by: []
pre-block-column: backburner
blocker-probe: trddgrep --porcelain show UP6VP41N
blocker-holds-if: match:\t(backburner|approval|design|design_ai_review|design_human_review|todo|verify_assumptions|plan|dispatch|dev|testing|ai_review|human_review|blocked|failed|proposal|planned)\t
blocker-probe-canary: match:UP6VP41N
---

# Per-scope index files and the gitignore line

Spec: design/specs/wikimem-layout-spec.md 0.2.8 (draft). Implements WL-10. Replace root/.memgrep/index.db with wm_local_index.db, wm_project_index.db and wm_user_index.db beside the pages, one per scope present in a folder; add a wm_*_index.db line to the project .gitignore and the USER repository so indexes stay out of git; record WL-CONF-1. Anchor: index.rs:33-35. Done when: each scope writes its own index beside its pages and no index file is tracked by git.

## Approval log

- 2026-10-23T17:57:00+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-23T18:03:31+0200 — column → blocked. waits on UP6VP41N
- 2026-10-24T03:20:11+0200 — column → backburner by main-agent@ai-maestro-janitor. blocker UP6VP41N complete (spec F23)
