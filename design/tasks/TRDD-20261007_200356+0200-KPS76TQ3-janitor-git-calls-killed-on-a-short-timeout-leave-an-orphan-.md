---
trdd-id: KPS76TQ3
title: Janitor git calls killed on a short timeout leave an orphan .git/index.lock
column: todo
status: tasked
created: 2026-10-07T20:03:56+0200
updated: 2026-10-10T23:36:58+0200
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
2026-10-07T20:20:21+0200: the lead is ruled out. Every read-only git call in scripts/ already sets GIT_OPTIONAL_LOCKS=0 (janitor#245), including the ci-status call through state.run_subprocess; its guard tests pass (12). The orphan locks more likely come from a git WRITER killed mid-operation (git add/commit in publish.py or project-plugins-update.py) or from a git process outside the janitor. Next step if it recurs: record the lock's mtime and the processes running then, and match them to the writer.

## STATE

2026-10-11 00:10 READ, not built (TRDD-S6GX1DHN wave 23 card 2). No orphan lock exists now (find on .git, with the index file as control). A detector already removes one: scripts/detectors/stale-index-lock.py, registered at 300 s in scripts/dispatch.py line 126, in place since 2026-08-14 (dc1af1ed). On a removal it prints one heartbeat line and writes NO log line; its dedupe key is forgotten on the next quiet pass. So a recurrence leaves no durable trace with a time, and this card cannot learn which writer was killed. No line of it was found in this project logs or state by a search for the detector name and for index.lock; that search did not identify the findings ledger file, so it proves little. NEXT ACTION, small and buildable: on the removed outcome write one state.log_line carrying the lock age and the git processes seen by the holder probe (read git_utils.clear_stale_index_lock first to see what it can return), with one test that drives a real stale lock in a temporary repository and reads the log. That turns this card from waiting on luck into waiting on a logged event. Stays in todo.
