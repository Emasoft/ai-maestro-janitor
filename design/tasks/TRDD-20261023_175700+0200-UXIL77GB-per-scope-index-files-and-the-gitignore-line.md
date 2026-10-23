---
trdd-id: UXIL77GB
title: Per-scope index files and the gitignore line
column: backburner
status: tasked
created: 2026-10-23T17:57:00+0200
updated: 2026-10-23T17:57:01+0200
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
spec: wikimem-layout-spec.md 0.2.3
---

# Per-scope index files and the gitignore line

Spec: design/specs/wikimem-layout-spec.md 0.2.3 (draft). Implements WL-10. Replace root/.memgrep/index.db with wm_local_index.db, wm_project_index.db and wm_user_index.db beside the pages, one per scope present in a folder; add a wm_*_index.db line to the project .gitignore and the USER repository so indexes stay out of git; record WL-CONF-1. Anchor: index.rs:33-35. Done when: each scope writes its own index beside its pages and no index file is tracked by git.

## Approval log

- 2026-10-23T17:57:00+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
