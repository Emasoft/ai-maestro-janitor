---
trdd-id: 4K7V0GFW
title: Post-compact resume and SessionStart TRDD injection ignore the linked worktree and treat human_review as in-flight
column: todo
status: tasked
created: 2026-11-18T01:25:36+0100
updated: 2026-11-18T01:27:08+0100
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
approval-datetime: 2026-11-18T01:25:36+0100
---

# Post-compact resume and SessionStart TRDD injection ignore the linked worktree and treat human_review as in-flight

Source: GitHub issue #365 (https://github.com/Emasoft/ai-maestro-janitor/issues/365), filed by another agent; its claims are unverified.

Owner order 2026-11-17 (verbatim): "convert those issues into TRDDs to solve all those issues and improve the whole janitor system migrating to mods most of its functionalities. but those TRDDs must be written now and handled later." Written now, handled later; TRDD-BAQB9SYO has priority.

## Symptom

By the issue: in a session launched in the main checkout but committing in a linked worktree inside the project, after each compaction the resume cue named a card that had been in human_review since 2026-11-15 (goal reached, waiting for the owner) instead of the session current goal card, which exists only in the worktree design folder. By the issue the SessionStart compact hook injected 4 cards from the main checkout, two of them stale copies of cards that are newer in the worktree, one a human_review card waiting on owner decisions, none with a STATE block; the worktree has 25 cards in the issue body, corrected to 24 by a comment, in the dev, testing, ai_review and human_review columns and none was considered.

## Suspected cause

By the issue: _inflight_trdd_directive picks the in-flight TRDD with the newest updated value under the project root, and the SessionStart collector takes its root from CLAUDE_PROJECT_DIR or the cwd; neither looks at the worktree the session works in. Both treat human_review as in-flight, so a card waiting for the human becomes a continue target. updated values are compared as strings, which is right only when every card has the same UTC offset, and this board mixes +0200 and +0100. Expected by the issue: collectors use the board of the worktree the session commits in, or all worktrees of the repo with duplicates resolved by the newest copy; human_review is not a continue target (at most listed as waiting for the human); updated values compared as datetimes. Related closed issues named by the issue: 267, 185, 264.

## Files named by the issue

scripts/hooks/post-compact-resume.py (lines 53-58 _INFLIGHT_COLUMNS, 166-218 _inflight_trdd_directive, the updated string comparison); scripts/hooks/on-session-start-trdd-state.py (line 74, line 251 _ACTIVE_COLUMNS).

## Done means

The defect is reproduced or shown absent, fixed with a test where one fits, and the issue is answered and closed.
Related card TRDD-WUIN2IGF (migrate most janitor functionality to Claude Code mods, owner order 2026-11-17) may move the component this fix touches; check it before fixing. Link only, no design rule.

## Approval log

- 2026-11-18T01:25:36+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
