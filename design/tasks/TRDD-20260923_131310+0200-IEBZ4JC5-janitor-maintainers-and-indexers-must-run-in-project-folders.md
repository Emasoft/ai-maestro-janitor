---
trdd-id: IEBZ4JC5
title: Janitor maintainers and indexers must run in project folders whose git repos live in subfolders
column: todo
created: 2026-09-23T13:13:10+0200
updated: 2026-09-25T16:27:02+0200
current-owner: janitor-main-session
created-by: Emasoft
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: Emasoft
approval-datetime: 2026-09-23T13:13:10+0200
---

# Janitor maintainers and indexers must run in project folders whose git repos live in subfolders

## Owner's directive (verbatim, 2026-09-23)

> i told you to make the memory maintainance agents and all other jsnitor maintainer subagents to detect if a project has a git folder that is not in the project root and act in a smart way to still execute the task. it is not uncommon for project folders to have many subfolders with different git folders. i don't know how to solve the fact that the design folder must be git tracked, or that the project scoped wikimem memories must be git tracked in those kind of projects folders too, honestly. But surely this must not prevent the librarians/maintainers agents from doing their maintainance jobs or the indexers to index those folders. the janitor must ensure that the maintainance is done.

## Requirement

A project folder that is not itself a git repository, or whose git repositories live only in subfolders (one or many), must still get every janitor maintenance job (memory chores, repair, security, TRDD/board detectors) and every indexer (memgrep, trddgrep) run. No job may silently skip or refuse because `git rev-parse --show-toplevel` fails or differs from the project root. Where the design folder and PROJECT-scope memory live in such a layout, and how they get git-tracked, is an open design question to be proposed to the owner.

## Prior partial work

ac39cf13 (memory-marker STATE_DIR recipe falls back to the cwd when there is no git); issue #66 (nested-repo descend in the PreCompact handoff git sections); issue #267 (the same descend applied to the TRDD collector).

## Approval log

- 2026-09-23T13:13:10+0200 — MANDATE issued by Emasoft (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

2026-09-25 15:55 — measured, proposal ready for the owner (no code — the card's layout question is owner-owned): (1) state.py's root ladder (env > override > rev-parse > cwd) and trdd_common.local_design_root (worktree/submodule-aware, non-repo = project dir stands) already resolve correctly for nested-repo projects; the LOCAL corpus never hoists into a subrepo. (2) The silent-skip class is real but bounded: memory-scope-leak, ci-status, dirty-tree, github-issues-watch, branch-protection, gitignore-coverage each fail-open with a graceful no-op when the project root is not itself a repo — their remedial half (gitignore coverage, dirty tree, GitHub config) is genuinely meaningless without a repo, so the only true gaps are the memory/trdd MAINTENANCE chores. (3) PROPOSAL for the owner, three options: (a) RECOMMENDED — when the project root is not a repo, maintenance jobs walk the immediate subfolders' repos for the git-bound halves (trddgrep board discovery, project-memory-tracked check) and treat design/ + .claude/project/memory at the PROJECT ROOT as the corpus home, git-tracked via whichever subfolder repo the owner registers in a small config file (.janitor/track-repo); (b) corpus lives inside ONE designated subrepo; (c) corpus stays untracked for such projects (status quo, with the no-op surfaced as a finding instead of silent). Decide (a)/(b)/(c) and I implement.
