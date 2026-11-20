---
trdd-id: 3MUWV3PJ
title: Session start prints the git-root error when trdd_common is absent, failing the silent-fallback test and blocking the publish
column: todo
status: tasked
created: 2026-11-20T06:07:20+0100
updated: 2026-11-20T06:18:15+0100
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

## Notes

- 2026-11-20T06:07:35+0100 main-agent lead: the test file was last touched by a12f276a (SWQXCIOS bandit lane: guard stderr notices and narrow log handlers in hooks) after ad6adb5e added the message; check whether a12f276a changed the trdd_common-absent path first.
- 2026-11-20T06:15:22+0100 main-agent: the publish log path in the body is local and gitignored. Cause (worker, shown by an import spy and a bisect: the test file passes 7 of 7 at a5b7027e^, fails 3 of 3 at HEAD): a5b7027e made the SessionStart hook call _git_toplevel first, which imports lib.exe_path from the hook's own tree, so a hook run from the real tree finds the real trdd_common whatever CLAUDE_PLUGIN_ROOT says; the test, not the hook, was wrong. In production the hook and its lib sit in the same plugin root, so nothing changes there. Fix: the test runs hook copies from inside the stripped root; the file passes 3 of 3; ruff, mypy, pyright clean. The lead on a12f276a was wrong (it only last touched the test).
- 2026-11-20T06:17:42+0100 main-agent: read of on-session-start-trdd-state.py:87-126 and 367-389: the CLAUDE_PLUGIN_ROOT import path is not dead after a5b7027e. _read_input calls _git_toplevel only when the payload carries cwd; with no cwd, lib is not cached and _trdd_paths imports trdd_common from CLAUDE_PLUGIN_ROOT/scripts. With cwd (the usual case), lib comes from the hook's own tree and the env entry only adds scripts/lib. The two-rule split is tracked as TRDD-TAPZ5XNV. The PostCompact test also runs a copy because post-compact-resume.py has the same _git_toplevel import of lib.exe_path (near line 291), so the same cache can form there; that test passed at HEAD, so the copy is preventive, not a fix of an observed failure. Cause and bisect are by the worker's report.
