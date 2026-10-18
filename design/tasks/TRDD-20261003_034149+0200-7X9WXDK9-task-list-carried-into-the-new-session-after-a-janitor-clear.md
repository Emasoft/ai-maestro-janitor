---
trdd-id: 7X9WXDK9
title: Task list carried into the new session after a janitor clear
column: testing
status: tasked
created: 2026-10-03T03:41:49+0200
updated: 2026-10-18T03:49:37+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:41:49+0200
project-id: ai-maestro-janitor

parent-trdd: K9AHY1ZB
derived: true
implementation-commits: [3bf497de]
---

# Task list carried into the new session after a janitor clear

- **C3**: copy the task directory only when all of these hold:
  - this is a janitor chain (a sidecar exists);
  - `CLAUDE_CODE_TASK_LIST_ID` is unset;
  - the old directory holds `*.json` (the file backend, not storageV5);
  - the new directory is empty.

  Skip `*.lock`, keep `.highwatermark`, and label it as relying on undocumented internals. Tests: copy, lock skipped, no overwrite, env set, no sidecar.

Parent plan: TRDD-K9AHY1ZB

## Approval log

- 2026-10-03T03:41:49+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-03T10:37:08+0200 — column → dev. C3 in progress
- 2026-10-03T10:44:40+0200 — column → testing. code ready; field check after release: after a janitor clear the new session's TaskList shows the open tasks
- 2026-10-03 C3 revision: new dir counts as having tasks only if it holds a json file; highwatermark raised never lowered. NOTE: the no-sidecar, env-set, no-json and no-overwrite tests passed trivially before the change; they are not regression proof.
2026-10-09 STAYS in testing (board drain, wave 3), one of two field checks now observed. (a) OBSERVED by the main session in session 8a11fda7, cleared at 09:40 on 2026-10-09: jev-post-clear-hook.log reads 'carried 2 task file(s)', and the first task reminder of the new session listed tasks 1 and 2 with their subjects and states. (b) NOT established: that the carried files still exist after the new session creates its first task; the session's task directory holds no json now, with all its tasks completed. Assessment: reports/board/20261009_232221+0200-wave3-batchD.md.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

Field check after release, both parts required before complete: (a) after a janitor clear, TaskList in the new session shows the carried tasks; (b) after the new session creates its first task, the carried N.json files still exist (rules out an in-memory list written back over the folder).
Unverified: that the transcript file stem equals the old sessionId in every case; a wrong id finds no *.json and copies nothing (fails safe).
Possible follow-up: carry only tasks whose status is not completed (matching the Continuity block's open_tasks), so the list does not grow across repeated clears; copy2 keeps old mtimes, harmless unless Claude Code orders tasks by mtime.
2026-10-05 — FIELD CHECK, from a worker's read of the logs, not re-read by the main agent: not exercised: 5 janitor clears after install (three on 2026-10-04, two on 2026-10-05), none of the cleared sessions had a task directory, 0 carried-files log lines; needs a clear of a session with a populated task directory. The card stays in testing; the check could not be made: no cleared session held task files.
2026-10-11 01:24. HALF MET, from reports/board/20261011_005026+0200-testing-sweep.md (a read-only worker; leads, not re-read by the main session unless said): two lines carried 2 task file(s) in .janitor/logs/jev-post-clear-hook.log (2026-10-09 07:31 session f2dd0f96, 09:40 session 8a11fda7); survival past the first new task creation is not shown. Stays in testing.
