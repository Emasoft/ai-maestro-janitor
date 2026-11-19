---
trdd-id: 0GZ5383A
title: Fifty-three agent worktrees under .claude/worktrees were never merged or removed
column: todo
status: tasked
created: 2026-11-19T23:33:09+0100
updated: 2026-11-19T23:53:27+0100
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

## Findings

2026-11-19 (main-agent): removed the 32 class-A worktrees (clean, every commit patch-equivalent in main) with plain git worktree remove, no force: removed=32 failed=0; their ignored reports/ folders (20, 4-224 KB) were moved first to reports_dev/retired-worktree-reports/<name>/. git worktree prune dropped 8 entries whose folders were gone. Branches worktree-agent-* are kept (no branch deleted). Free space 174 GB to 192 GB. Left alone: 2 class B with unmerged patches (fix/prrd-bootstrap-init carries 5 patches described as USER-approved rule edits; retired agent-ad55b68799d2d9c8c 2 patches TRDD-8BNV75TV) and 11 class C with uncommitted tracked edits, each needing its own judgment. wt2 (session scratchpad): its changes are already in main via 6a316641 (test file identical, memory_dispatch_claim.py differs only by a later exe() import). Root-cause lead, not yet read: scripts/detectors/worktree-janitor.py:175 skips a merged worktree whose branch has no upstream, and every worktree-agent-* branch has none. Audit: reports_dev/sonnet-worker/20261119_233758+0100-0gz5383a-worktree-audit.md.
