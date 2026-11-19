---
trdd-id: 4K7V0GFW
title: Post-compact resume and SessionStart TRDD injection ignore the linked worktree and treat human_review as in-flight
column: todo
status: tasked
created: 2026-11-18T01:25:36+0100
updated: 2026-11-20T00:13:08+0100
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
implementation-commits: [486a7367]
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
- 2026-11-18T16:38:21+0100 — progress, by cheap-worker for main-agent: implementation-commits set to [486a7367]. Per main-agent evidence: human_review removed from _INFLIGHT_COLUMNS (post-compact-resume.py) and from _ACTIVE_COLUMNS (on-session-start-trdd-state.py); updated values compared as datetimes (_updated_epoch). Files of 486a7367 (git show --stat): scripts/hooks/post-compact-resume.py, scripts/hooks/on-session-start-trdd-state.py, tests/test_post_compact_resume_hook.py, tests/test_trdd_state_hook.py. The worktree half of issue 365 stays open; the Measured section is the entry stamped 2026-11-18T16:43:47+0100 below, copied from reports_dev/main-agent/post1/issue365-worktree-half.md (local), per main-agent evidence, not checked by cheap-worker. Card not moved: a GitHub issue answer (issue 365) comes first.
- 2026-11-18T16:43:47+0100 — copy, by cheap-worker for main-agent, of the Measured section of reports_dev/main-agent/post1/issue365-worktree-half.md (local), one entry; per main-agent evidence, not checked by cheap-worker. Measured 2026-11-18 by grep of the two hooks:
  - scripts/hooks/on-session-start-trdd-state.py reads the hook stdin field cwd first (line 69), then CLAUDE_PROJECT_DIR, then os.getcwd (line 83). The SessionStart half therefore already reads the board of the hook-input cwd.
  - scripts/hooks/post-compact-resume.py reads the payload cwd only as a fallback when CLAUDE_PROJECT_DIR is absent (lines 738-788).
  Consequence: option A (read the board of the hook-input cwd) does not cover the case the issue reports. That session was launched in the main checkout and committed in a linked worktree; the Bash tool cwd does not persist, so the hook-input cwd stays the main checkout and option A reads the same main board as today.
  Candidate signals still open:
  - the worktree named by the session recent git -C or absolute-path commits, read from the transcript;
  - the worktree holding the most recent commit made by this session;
  - all worktrees of the repo, newest copy wins. Weak: about 40 .claude/worktrees/agent-* worktrees exist (many marked prunable), so abandoned cards would become resume targets.
  Consistency follow-up, not changed by 486a7367: scripts/detectors/trdd-reminder.py:58 (_ACTIVE_COLUMNS) and scripts/hooks/pre-compact-handoff.py:121 still include human_review. The handoff may legitimately list cards waiting for the human; decide per module.
- 2026-11-18T16:49:55+0100 — correction, by main-agent: the entry of 2026-11-18T16:43:47+0100 states two premises as fact that are not verified for the reporting session: that its hook-input cwd was the main checkout, and that its Bash cwd did not persist (both hold in this harness, not shown for that session). So option A is not shown to help, rather than ruled out; the worktree half stays open. Measured facts in that entry (the two hooks read the hook-input cwd as described, lines 69, 83 and 738-788) stand.

## Findings

2026-11-20 main-agent, from reports_dev/sonnet-worker/20261120_000405+0100-47MHZ2YF-4K7V0GFW.md (code read, not mutation-proven): first half landed at 486a7367 (human_review out of _INFLIGHT_COLUMNS post-compact-resume.py:53-58 and _ACTIVE_COLUMNS on-session-start-trdd-state.py:264; updated compared as an instant via _updated_epoch post-compact-resume.py:209-214). Open: (1) the worktree board choice; (2) the two hooks disagree on root precedence: post-compact-resume.py:763-764 reads payload cwd only when CLAUDE_PROJECT_DIR is unset, on-session-start-trdd-state.py:59-84 reads payload cwd first; (3) _record_resume_directive uses state.project_root() for the board AND state.state_dir() for the flag, so a board-root change must not move the flag; (4) human_review still in trdd-reminder.py:58 and pre-compact-handoff.py:139; (5) SessionStart takes _in_progress(...)[:MAX_TRDDS] in filename order, so with more than 4 active cards the newest can be dropped. DECISION (main-agent, 2026-11-20, open to owner veto): the board root is the worktree the session actually runs in, i.e. the hook payload cwd resolved to its git toplevel, then CLAUDE_PROJECT_DIR, then os.getcwd, in BOTH hooks; the resume flag stays under the main checkout state dir; trdd-reminder drops human_review (a reminder to work on it is wrong), pre-compact-handoff keeps listing it as waiting for the human; SessionStart orders by updated: newest first before the cap.
