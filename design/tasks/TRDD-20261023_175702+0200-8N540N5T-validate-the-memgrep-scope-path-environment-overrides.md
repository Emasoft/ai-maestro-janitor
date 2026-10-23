---
trdd-id: 8N540N5T
title: Validate the memgrep scope path environment overrides
column: backburner
status: tasked
created: 2026-10-23T17:57:02+0200
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
approval-datetime: 2026-10-23T17:57:02+0200
relevant-rules: [13, 14, 18]
spec: wikimem-layout-spec.md 0.2.3
---

# Validate the memgrep scope path environment overrides

Spec: design/specs/wikimem-layout-spec.md 0.2.3 (draft). Implements WL-11. At parse time PROJECT must resolve inside the project root and not be gitignored; LOCAL inside the project root or a project slug folder; USER not inside any other git repository; on violation memgrep warns and uses the default path. Anchor: memory.rs:6719-6728. Done when: each rule has a real test with a violating value.

## Approval log

- 2026-10-23T17:57:02+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
