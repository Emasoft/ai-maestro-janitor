---
trdd-id: IEBZ4JC5
title: Janitor maintainers and indexers must run in project folders whose git repos live in subfolders
column: todo
created: 2026-09-23T13:13:10+0200
updated: 2026-09-23T13:13:10+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: bugfix
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
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

- 2026-09-23T13:13:10+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
