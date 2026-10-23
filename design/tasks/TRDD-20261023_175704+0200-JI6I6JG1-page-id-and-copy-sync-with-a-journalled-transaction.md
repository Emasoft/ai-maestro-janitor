---
trdd-id: JI6I6JG1
title: Page id and copy sync with a journalled transaction
column: blocked
status: tasked
created: 2026-10-23T17:57:04+0200
updated: 2026-10-23T20:24:09+0200
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
spec: wikimem-layout-spec.md 0.2.8
npt: []
blocked-by: [W17F82DN]
pre-block-column: backburner
blocker-probe: trddgrep --porcelain show W17F82DN
blocker-holds-if: match:\t(backburner|approval|design|design_ai_review|design_human_review|todo|verify_assumptions|plan|dispatch|dev|testing|ai_review|human_review|blocked|failed|proposal|planned)\t
blocker-probe-canary: match:W17F82DN
---

# Page id and copy sync with a journalled transaction

Spec: design/specs/wikimem-layout-spec.md 0.2.8 (draft). Implements WL-13, WL-14, WL-15, WL-16. Add page-id: PAGE-XXXX-XXXX to every page; copies share a page-id; a write is applied to every visible copy in one journalled transaction holding all affected scope locks; atom ids may repeat only across files sharing a page-id; diverged copies are reported as page-copies-diverged and writes refused until memgrep reconcile resolves them; cross-project copies refresh pull-on-access. Anchors: pre_write.rs ~215-275, memory.rs atomic_write_page:2839. Done when: editing one copy updates all, divergence is detected and refused, and reconcile works, all with real tests.

## Approval log

- 2026-10-23T17:57:04+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-23T18:03:48+0200 — column → blocked. waits on W17F82DN
- 2026-10-23T20:24+0200 — NOTE (main session): its only blocker W17F82DN (VERIFY-4) is complete, but its result (spec WL-FACT F18) is that no stored project-id exists without 3-pillars cards and neither origin URL nor root commit is unique alone. Before this card moves to dev, the project-id rule must be decided and written into the spec; this card must not start without it.
