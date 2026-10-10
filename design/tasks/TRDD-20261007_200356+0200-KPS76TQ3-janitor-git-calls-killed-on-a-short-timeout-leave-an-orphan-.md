---
trdd-id: KPS76TQ3
title: Janitor git calls killed on a short timeout leave an orphan .git/index.lock
column: backburner
status: tasked
created: 2026-10-07T20:03:56+0200
updated: 2026-10-11T00:06:37+0200
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
blocker-probe: find "$(git rev-parse --show-toplevel)/.git" -maxdepth 1 -name 'index.lock.stale-*' -newermt 2026-10-11
blocker-holds-if: not-match:index.lock.stale
review-after: 2026-12-10
---

# Janitor git calls killed on a short timeout leave an orphan .git/index.lock

Two empty, holder-less .git/index.lock files appeared in this repo on 2026-10-07 (one removed at about 16:53 by the main agent, one moved to reports_dev/stale-index.lock-9kk by a worker). Lead: the heartbeat logged `[run_subprocess] ci-status subprocess timed out after 10s: git`; a git killed on timeout while holding index.lock leaves it behind. Scope: list the detectors and hooks that run index-touching git commands (status refreshes the index; add, commit) with short timeouts; pass `--no-optional-locks` (or GIT_OPTIONAL_LOCKS=0) to every read-only status call so it never takes the lock; see the memory page git-index-lock-orphan-recovery.

## Approval log

- 2026-10-07T20:03:56+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-07T20:20:21+0200: the lead is ruled out. Every read-only git call in scripts/ already sets GIT_OPTIONAL_LOCKS=0 (janitor#245), including the ci-status call through state.run_subprocess; its guard tests pass (12). The orphan locks more likely come from a git WRITER killed mid-operation (git add/commit in publish.py or project-plugins-update.py) or from a git process outside the janitor. Next step if it recurs: record the lock's mtime and the processes running then, and match them to the writer.
- 2026-10-11T00:06:37+0200 — column → backburner. measured: 46 past orphan locks, a fifth near a heartbeat fire, most unexplained; the detector heals it; pull on a new stale file

## STATE

2026-10-11 00:10 READ, not built (TRDD-S6GX1DHN wave 23 card 2). No orphan lock exists now (find on .git, with the index file as control). A detector already removes one: scripts/detectors/stale-index-lock.py, registered at 300 s in scripts/dispatch.py line 126, in place since 2026-08-14 (dc1af1ed). On a removal it prints one heartbeat line and writes NO log line; its dedupe key is forgotten on the next quiet pass. So a recurrence leaves no durable trace with a time, and this card cannot learn which writer was killed. No line of it was found in this project logs or state by a search for the detector name and for index.lock; that search did not identify the findings ledger file, so it proves little. NEXT ACTION, small and buildable: on the removed outcome write one state.log_line carrying the lock age and the git processes seen by the holder probe (read git_utils.clear_stale_index_lock first to see what it can return), with one test that drives a real stale lock in a temporary repository and reads the log. That turns this card from waiting on luck into waiting on a logged event. Stays in todo.
2026-10-10 23:51 (time read from the clock) CORRECTION, the line above is WRONG where it says a removal leaves no durable trace. git_utils.clear_stale_index_lock does not delete the lock, it renames it to index.lock.stale-EPOCH inside .git, so the file name carries the removal time and the file time carries the moment the lock was made. MEASURED now in this repository: 46 such files, every one empty, locks made from 2026-08-14 to 2026-10-05 14:23 (by day, at most 5, on 08-21 and 09-18); age at removal 71 s at least, 2019 s at the median. None is dated after 2026-10-05, and the two locks of 2026-10-07 named by this card were removed by hand, so they are not among them. An empty lock means git died right after creating it and before writing. FIRST MATCHING, four of the newest locks against this project logs and commits, NOT conclusive: 2026-10-04 14:15:37 follows a heartbeat fire by 31 s and a detached plugin-update worker by 25 s; 2026-10-04 18:21:10 follows a fire by 43 s; 2026-10-05 10:15:09 follows two commits by 100 s and has no log line in its three minutes; 2026-10-05 14:23:04 has no line before it in its minute. So the build named above is NOT needed for a trace. NEXT ACTION instead: match all 46 lock times against heartbeat fires, commits and the detached workers logs, and count how many fall within a minute after a fire; if most do, read which fire-time git writer runs without waiting for its child. Also open: 46 empty files are left in .git forever, nothing prunes them.
2026-10-11 00:06 (clock) ALL 46 MATCHED against this project heartbeat fires (8009 in the fire log, which spans all 46) and every commit time: 9 locks were made within 60 s after a fire, 9 within 120 s after a commit, 1 within 120 s before a commit, 27 match none. Chance alone puts 8.2 percent of clock time within 60 s after a fire, so 9 of 46 (20 percent) is above chance and still a fifth of the cases: a fire-time git writer is not the main cause, and most locks come from a git process these logs do not record. ACCEPTED from the review of 7ef8c348: not all 46 are the detector removals (publish.py and project-plugins-update.py rename locks the same way, one file has a hand-made name, and the youngest was removed at 71 s, under the detector 1800 s threshold); the file time equals the lock creation time only if the rename kept it and nothing touched the file since; an empty lock means git died right after creating it is an inference; and the files carry no process list, which is what this card first asked for. DECISION by the main session under the drain mandate: PARKED in backburner, no code. The detector heals the symptom within 30 minutes, no orphan is recorded since 2026-10-05 beyond the two removed by hand on 2026-10-07, and the cause is mostly outside what this project can see. PULL CONDITION, observable: a new index.lock.stale file in .git dated after 2026-10-11; the probe lists such files (run now, prints nothing; with 2026-10-04 as the date it lists 5). When it trips, the first step is the build withdrawn above, a log line at removal with the git processes then running. Left open: nothing prunes the 46 empty files.
