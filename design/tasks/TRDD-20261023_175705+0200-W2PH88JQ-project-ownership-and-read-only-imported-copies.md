---
trdd-id: W2PH88JQ
title: Project ownership and read-only imported copies
column: blocked
status: tasked
created: 2026-10-23T17:57:05+0200
updated: 2026-10-23T18:03:48+0200
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
npt: [W17F82DN]
relevant-rules: [13, 14, 19, 20, 21]
spec: wikimem-layout-spec.md 0.2.5
blocked-by: [JI6I6JG1]
pre-block-column: backburner
blocker-probe: trddgrep --design-dir /Volumes/EmaUITEK4TBSSD/Code/AI-MAESTRO-JANITOR/ai-maestro-janitor/design --porcelain show JI6I6JG1
blocker-holds-if: match:\t(backburner|blocked|todo|plan|dev|testing)\t
blocker-probe-canary: match:JI6I6JG1
---

# Project ownership and read-only imported copies

Spec: design/specs/wikimem-layout-spec.md 0.2.5 (draft). Implements WL-17, WL-18. PROJECT and LOCAL pages carry project-id; a write from a project with a different id is refused; USER pages are editable anywhere; publish-globally pages are read-only outside their project; an imported copy keeps the owner's page-id and project-id, is read-only, and is forked into a new page-id to edit. Anchor: memory.rs ~7158 (publish-globally symlink). Done when: cross-project writes are refused and forking works.

## Approval log

- 2026-10-23T17:57:05+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-23T18:03:47+0200 — column → blocked. waits on JI6I6JG1
