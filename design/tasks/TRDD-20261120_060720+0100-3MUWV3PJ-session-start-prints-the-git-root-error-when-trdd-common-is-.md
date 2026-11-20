---
trdd-id: 3MUWV3PJ
title: Session start prints the git-root error when trdd_common is absent, failing the silent-fallback test and blocking the publish
column: todo
status: tasked
created: 2026-11-20T06:07:20+0100
updated: 2026-11-20T06:07:20+0100
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
approval-datetime: 2026-11-20T06:07:20+0100
---

# Session start prints the git-root error when trdd_common is absent, failing the silent-fallback test and blocking the publish

Observed 2026-11-20 06:03 in the fourth publish.py --patch run (local log reports_dev/main-agent/publish-20261120_060303+0100.txt): pytest 1 failed, 6474 passed: tests/test_git_root_error_hooks.py::test_session_start_without_trdd_common_falls_back_to_project_glob_silently. The SessionStart output contained '[janitor-trdd] git failed resolving the design root (git worktree list --porcelain failed (exit 1) ...: boom); LOCAL-scope cards are not shown this time', which the test requires to be absent when trdd_common is not importable. The secret-shield and liveness gates passed in the same run at load 104 (start) to 62 (end). Needed: read the test and the session-start design-root path, decide whether the hook or the test is wrong, fix the cause, run that test file alone.

## Approval log

- 2026-11-20T06:07:20+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
