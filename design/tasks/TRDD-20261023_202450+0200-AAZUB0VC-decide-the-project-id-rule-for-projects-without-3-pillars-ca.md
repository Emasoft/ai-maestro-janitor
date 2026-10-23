---
trdd-id: AAZUB0VC
title: Decide the project-id rule for projects without 3-pillars cards
column: blocked
status: tasked
created: 2026-10-23T20:24:50+0200
updated: 2026-10-23T20:27:33+0200
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
approval-datetime: 2026-10-23T20:24:50+0200
relevant-rules: [24, 25, 26]
blocked-by: [JE53ZDPS]
pre-block-column: todo
blocker-probe: trddgrep --porcelain show JE53ZDPS
blocker-holds-if: match:\t(backburner|approval|design|design_ai_review|design_human_review|todo|verify_assumptions|plan|dispatch|dev|testing|ai_review|human_review|blocked|failed|proposal|planned)\t
blocker-probe-canary: match:JE53ZDPS
---

# Decide the project-id rule for projects without 3-pillars cards

Spec design/specs/wikimem-layout-spec.md WL-FACT F18 (VERIFY-4, TRDD-W17F82DN) shows that a project without 3-pillars cards has no stored project-id, and that neither the origin URL nor the root commit is unique on its own. Decide the rule the resolver and page-id sync use, base it on F18 and on any VERIFY result still open, and write it into the spec normative section with a version bump. Acceptance: the rule is in the spec; each case F18 names (no origin, no commits, several roots, copies of one project, forks, same-name repos) has a stated outcome; JI6I6JG1 can then be released.

## Approval log

- 2026-10-23T20:24:50+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-23T20:26:30+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on VERIFY-12 (JE53ZDPS), which measures the project-id markers the rule consumes
- 2026-10-23T20:27+0200 — ACCEPTANCE AMENDED (main session): forks and two different repos with the same name were not measured (spec F18). Their outcomes in the rule must be labelled as design choices, with that unmeasured status stated in the spec; they are not facts.
