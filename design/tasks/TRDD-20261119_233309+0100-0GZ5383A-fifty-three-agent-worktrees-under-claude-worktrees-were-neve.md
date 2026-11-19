---
trdd-id: 0GZ5383A
title: Fifty-three agent worktrees under .claude/worktrees were never merged or removed
column: todo
status: tasked
created: 2026-11-19T23:33:09+0100
updated: 2026-11-19T23:33:09+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-19T23:33:09+0100
---

# Fifty-three agent worktrees under .claude/worktrees were never merged or removed

2026-11-19: git worktree list shows 54 entries (53 linked) and .claude/worktrees holds 39 agent-* folders, each with full copies of the repo. Every finished worktree agent should have produced a merge task and then a removal (rule git-and-destructive-safety). Audit each one read-only: branch, ahead/behind main, uncommitted changes, whether its commits are already in main (git cherry). Then for each: merge what is unmerged and wanted, remove the clean and fully merged ones with git worktree remove (which refuses a dirty tree), and list the rest for the owner. Never force-remove; git can restore a removed clean worktree from its branch. Also find out which flow keeps creating them without cleanup.

## Approval log

- 2026-11-19T23:33:09+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
