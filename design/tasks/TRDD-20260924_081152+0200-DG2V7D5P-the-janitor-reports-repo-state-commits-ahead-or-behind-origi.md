---
trdd-id: DG2V7D5P
title: The janitor reports repo state, commits ahead or behind origin, and commits made outside publish.py
column: todo
created: 2026-09-24T08:11:52+0200
updated: 2026-09-24T08:11:52+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T08:11:52+0200
---

# The janitor reports repo state, commits ahead or behind origin, and commits made outside publish.py

no detector computes ahead/behind. main was 157 commits ahead of the last release on 2026-09-24 and nothing reported it. dirty-tree.py reads only `git status --porcelain`. branch-protection.py covers rulesets only. Report ahead/behind per branch, and flag a default-branch commit not made through publish.py.

## Approval log

- 2026-09-24T08:11:52+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
