---
trdd-id: KQULEGL2
title: Measure whether Claude Code cleanup ever touches the slug design folder
column: complete
status: archived
created: 2026-10-23T17:56:13+0200
updated: 2026-10-24T00:09:14+0200
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
approval-datetime: 2026-10-23T17:56:13+0200
relevant-rules: [13, 14, 15]
spec: wikimem-layout-spec.md 0.2.8
---

# Measure whether Claude Code cleanup ever touches the slug design folder

Spec: design/specs/wikimem-layout-spec.md 0.2.8 (draft). VERIFY-3 restated: The docs list only session files for the sweep (F4). Check, by observation and source if available, that a design/ folder under a slug folder is never deleted or emptied. Blocks: WL-2 and its migration (TRDD-M5BRPISQ). Done when: the measurement is recorded as a fact in the spec's WL-FACT section with its evidence.

## Approval log

- 2026-10-23T17:56:13+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-24T00:09:14+0200 — COMPLETE by main-agent@ai-maestro-janitor. measured; spec F22.

## Acceptance criteria

- [x] Measured from the Claude Code 2.1.309 binary (strings dump, key snippets re-found by the main session) and by observation (a 100-day-old card survives with cleanupPeriodDays 90): the cleanup never deletes a non-empty <slug>/design/; an empty one can be rmdir-ed. Recorded as spec WL-FACT F22.
