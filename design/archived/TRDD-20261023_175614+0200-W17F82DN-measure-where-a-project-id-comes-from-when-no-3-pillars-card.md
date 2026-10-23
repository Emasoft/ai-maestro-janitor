---
trdd-id: W17F82DN
title: Measure where a project-id comes from when no 3-pillars cards exist
column: complete
status: archived
created: 2026-10-23T17:56:14+0200
updated: 2026-10-23T20:22:43+0200
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
approval-datetime: 2026-10-23T17:56:14+0200
relevant-rules: [13, 14, 19]
spec: wikimem-layout-spec.md 0.2.8
---

# Measure where a project-id comes from when no 3-pillars cards exist

Spec: design/specs/wikimem-layout-spec.md 0.2.8 (draft). VERIFY-4 restated: The project-id is a repo name today (F15); find out how to obtain it for a project without cards and whether two projects can share one. Candidates to measure: the git remote URL and the root commit hash. Blocks: WL-17, WL-18, automatic adoption in WL-4, the page-id card JI6I6JG1 and the project ownership card. Done when: the measurement is recorded as a fact in the spec's WL-FACT section with its evidence.

## Approval log

- 2026-10-23T17:56:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-23T20:22+0200 — RESULT (main session, owner mandate of 2026-10-09): measured read-only on 57 local git repos (reports/board/20261023_202139+0200-W17F82DN-verify4.md; two results re-checked by the main session: ANIME2SVG has 4 root commits, CCProjectManager has no commits and no origin). Without 3-pillars cards no project-id is stored; 14 of 57 repos lack an origin remote, 5 have no commits; copies of one project share root commit and URL; neither candidate is unique on its own. Recorded as spec WL-FACT F18. The id rule itself is a design decision for SQBTMGYW/W2PH88JQ, not this spike. Not measured: a real fork, two repos with the same name.
- 2026-10-23T20:22:43+0200 — COMPLETE by main-agent@ai-maestro-janitor. VERIFY-4 measured; result is spec WL-FACT F18.

## Acceptance checklist

- [x] Measured, read-only, where a project-id could come from when no 3-pillars card exists (origin URL and root commit across 57 local repos), with the commands in the report.
- [x] The result is recorded in design/specs/wikimem-layout-spec.md as WL-FACT F18, including what was not measured.
