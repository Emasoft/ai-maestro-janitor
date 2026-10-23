---
trdd-id: JI6I6JG1
title: Page id and copy sync with a journalled transaction
column: backburner
status: tasked
created: 2026-10-23T17:57:04+0200
updated: 2026-10-23T17:57:04+0200
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
approval-datetime: 2026-10-23T17:57:04+0200
relevant-rules: [13, 14, 19, 20, 21]
spec: wikimem-layout-spec.md 0.2.3
---

# Page id and copy sync with a journalled transaction

Spec: design/specs/wikimem-layout-spec.md 0.2.3 (draft). Implements WL-13, WL-14, WL-15, WL-16. Add page-id: PAGE-XXXX-XXXX to every page; copies share a page-id; a write is applied to every visible copy in one journalled transaction holding all affected scope locks; atom ids may repeat only across files sharing a page-id; diverged copies are reported as page-copies-diverged and writes refused until memgrep reconcile resolves them; cross-project copies refresh pull-on-access. Anchors: pre_write.rs ~215-275, memory.rs atomic_write_page:2839. Done when: editing one copy updates all, divergence is detected and refused, and reconcile works, all with real tests.

## Approval log

- 2026-10-23T17:57:04+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
