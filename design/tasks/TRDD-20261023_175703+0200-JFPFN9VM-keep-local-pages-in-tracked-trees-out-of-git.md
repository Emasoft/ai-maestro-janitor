---
trdd-id: JFPFN9VM
title: Keep local pages in tracked trees out of git
column: blocked
status: tasked
created: 2026-10-23T17:57:03+0200
updated: 2026-10-23T18:10:19+0200
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
approval-datetime: 2026-10-23T17:57:03+0200
npt: [P1EOHL6A]
relevant-rules: [13, 14, 18]
spec: wikimem-layout-spec.md 0.2.8
blocked-by: [V45G0MDV]
pre-block-column: backburner
blocker-probe: trddgrep --porcelain show V45G0MDV
blocker-holds-if: match:\t(backburner|approval|design|design_ai_review|design_human_review|todo|verify_assumptions|plan|dispatch|dev|testing|ai_review|human_review|blocked|failed|proposal|planned)\t
blocker-probe-canary: match:V45G0MDV
---

# Keep local pages in tracked trees out of git

Spec: design/specs/wikimem-layout-spec.md 0.2.8 (draft). Implements WL-12. A local page inside a git work tree is excluded by a memgrep-managed block in .git/info/exclude; before every write and in lint memgrep runs git check-ignore and refuses the write if git would track the page. Relies on VERIFY-8 for linked worktrees. Done when: the block is managed idempotently and a tracked local page is refused in a plain repository and a linked worktree.

## Approval log

- 2026-10-23T17:57:03+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-23T18:03:49+0200 — column → blocked. waits on V45G0MDV
