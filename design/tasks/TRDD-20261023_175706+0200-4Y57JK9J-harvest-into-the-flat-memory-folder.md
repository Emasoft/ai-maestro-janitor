---
trdd-id: 4Y57JK9J
title: Harvest into the flat memory folder
column: blocked
status: tasked
created: 2026-10-23T17:57:06+0200
updated: 2026-10-23T18:10:21+0200
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
approval-datetime: 2026-10-23T17:57:06+0200
npt: [YG6NMKJA]
relevant-rules: [13, 14, 16]
spec: wikimem-layout-spec.md 0.2.8
blocked-by: [KLT5F93P]
pre-block-column: backburner
blocker-probe: trddgrep --porcelain show KLT5F93P
blocker-holds-if: match:\t(backburner|approval|design|design_ai_review|design_human_review|todo|verify_assumptions|plan|dispatch|dev|testing|ai_review|human_review|blocked|failed|proposal|planned)\t
blocker-probe-canary: match:KLT5F93P
---

# Harvest into the flat memory folder

Spec: design/specs/wikimem-layout-spec.md 0.2.8 (draft). Implements WL-20. The harvest chore keeps copying Claude Code raw notes without editing them (TRDD-ab232dbd) and lands wikimem pages in the flat folder; the indexer ignores raw notes because they lack node_type and tier; the write-path hook must allow Claude Code to write its own notes there. Anchor: skills/janitor-memory-harvest/SKILL.md. Done when: harvested pages land flat and raw notes are untouched and unindexed.

## Approval log

- 2026-10-23T17:57:06+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-23T18:03:46+0200 — column → blocked. waits on KLT5F93P
