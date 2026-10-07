---
trdd-id: KPS76TQ3
title: Janitor git calls killed on a short timeout leave an orphan .git/index.lock
column: todo
status: tasked
created: 2026-10-07T20:03:56+0200
updated: 2026-10-07T20:03:56+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T20:03:56+0200
---

# Janitor git calls killed on a short timeout leave an orphan .git/index.lock

Two empty, holder-less .git/index.lock files appeared in this repo on 2026-10-07 (one removed at about 16:53 by the main agent, one moved to reports_dev/stale-index.lock-9kk by a worker). Lead: the heartbeat logged `[run_subprocess] ci-status subprocess timed out after 10s: git`; a git killed on timeout while holding index.lock leaves it behind. Scope: list the detectors and hooks that run index-touching git commands (status refreshes the index; add, commit) with short timeouts; pass `--no-optional-locks` (or GIT_OPTIONAL_LOCKS=0) to every read-only status call so it never takes the lock; see the memory page git-index-lock-orphan-recovery.

## Approval log

- 2026-10-07T20:03:56+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
