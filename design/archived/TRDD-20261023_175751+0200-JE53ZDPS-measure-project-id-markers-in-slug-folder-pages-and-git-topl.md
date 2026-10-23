---
trdd-id: JE53ZDPS
title: Measure project-id markers in slug folder pages and git toplevel through a symlink
column: complete
status: archived
created: 2026-10-23T17:57:51+0200
updated: 2026-10-23T20:47:29+0200
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
approval-datetime: 2026-10-23T17:57:51+0200
relevant-rules: [13, 14, 15, 19, 24, 25]
spec: wikimem-layout-spec.md 0.2.8
---

# Measure project-id markers in slug folder pages and git toplevel through a symlink

Spec: design/specs/wikimem-layout-spec.md 0.2.8 (draft). VERIFY-12 restated: count the existing slug folders with memory pages whose project-id or scope names their project, and find what git rev-parse --show-toplevel returns for a launch cwd reached through a symlink such as ~/Code. Blocks: the adoption rule and the canonical-path comparison of WL-4, and the slug-set resolver card SQBTMGYW. Done when: the measurement is recorded as a fact in the spec's WL-FACT section with its evidence.

## Approval log

- 2026-10-23T17:57:51+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-23T20:47+0200 — RESULT (main session): worker counted 949 pages in 89 folders, the main session's re-run gives 907 top-level .md pages in 88 non-empty folders (the worker likely counted nested files); both find zero frontmatter project-id or scope keys. Recorded as F19.
- 2026-10-23T20:47:29+0200 — COMPLETE by main-agent@ai-maestro-janitor. VERIFY-12 measured; spec WL-FACT F19.

## Acceptance checklist

- [x] Measured read-only: project-id or scope keys in slug-folder memory pages (none) and git toplevel through a symlink (resolved path); recorded as spec WL-FACT F19.
