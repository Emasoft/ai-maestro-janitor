---
trdd-id: 56FOY1U1
title: Other git worktree list callers still print a full traceback when the command fails
column: backburner
status: tasked
created: 2026-11-16T15:08:40+0100
updated: 2026-11-16T15:08:40+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-16T15:08:40+0100
---

# Other git worktree list callers still print a full traceback when the command fails

Follow-up of TRDD-YL732I8X. YL732I8X fixed only ticket dispatch: a git worktree list timeout now prints one stderr line and exits 1 there. The same unhandled RuntimeError (raised by trdd_common._main_checkout_root when git worktree list fails) still reaches these callers, which YL732I8X lists as uncovered:

- trdd-drift
- trdd-reminder
- trdd-state-reconciliation
- trdd-cross-card-blindspot
- report-to-trdd-drift
- the SessionStart trdd-state hook
- dispatch.py

## Acceptance

- [ ] each listed caller degrades to one line instead of a traceback when git worktree list fails
- [ ] a test per caller

## Approval log

- 2026-11-16T15:08:40+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
