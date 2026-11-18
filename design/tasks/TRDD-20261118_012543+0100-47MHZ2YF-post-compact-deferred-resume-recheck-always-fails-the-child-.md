---
trdd-id: 47MHZ2YF
title: Post-compact deferred resume recheck always fails, the child reuses a temporary uv Python that is gone
column: todo
status: tasked
created: 2026-11-18T01:25:43+0100
updated: 2026-11-18T16:38:09+0100
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
approval-datetime: 2026-11-18T01:25:43+0100
implementation-commits: [486a7367]
---

# Post-compact deferred resume recheck always fails, the child reuses a temporary uv Python that is gone

Source: GitHub issue #368 (https://github.com/Emasoft/ai-maestro-janitor/issues/368), filed by another agent; its claims are unverified.

Owner order 2026-11-17 (verbatim): "convert those issues into TRDDs to solve all those issues and improve the whole janitor system migrating to mods most of its functionalities. but those TRDDs must be written now and handled later." Written now, handled later; TRDD-BAQB9SYO has priority.

## Symptom

By the issue: when a compaction happens while the user is attended, the post-compact resume push is deferred by 60 s and the deferred recheck then raises FileNotFoundError for a missing python under a temporary uv build folder; 49 such lines are in the log across 2026-11-16 to 2026-11-18, so by the issue the resume push never fires after an attended compaction.

## Suspected cause

By the issue (read in source, not traced at run time): the hook runs under uv run --script, so sys.executable is the Python of a temporary uv environment; the deferred child is started with that interpreter and, 60 s later, starts the trigger with it again, by which time the hook has exited and uv removed the environment. Expected by the issue: the deferred child and anything it starts use an interpreter that outlives the hook (for example uv run --script on the trigger again, or a stable Python resolved before exit), and the log shows the push firing or why it was skipped.

## Files named by the issue

scripts/hooks/post-compact-resume.py (line 1 shebang, line 446 trigger start, line 477 deferred child start); per-project .janitor/logs/post-compact-resume.log.

## Done means

The defect is reproduced or shown absent, fixed with a test where one fits, and the issue is answered and closed.
Related card TRDD-WUIN2IGF (migrate most janitor functionality to Claude Code mods, owner order 2026-11-17) may move the component this fix touches; check it before fixing. Link only, no design rule.

## Approval log

- 2026-11-18T01:25:43+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-18T16:38:09+0100 — progress, by cheap-worker for main-agent: implementation-commits set to [486a7367]. Per main-agent evidence: detached children start on realpath(sys.executable) via _stable_python, which raises when that is not an executable file. Files of 486a7367 (git show --stat): scripts/hooks/post-compact-resume.py, scripts/hooks/on-session-start-trdd-state.py, tests/test_post_compact_resume_hook.py, tests/test_trdd_state_hook.py. Card not moved: a GitHub issue answer (issue 368) comes first.
