---
trdd-id: AFW0CA65
title: Two elided-id links of a post-clear handoff do not resolve
column: todo
status: tasked
created: 2026-10-10T03:51:17+0200
updated: 2026-10-10T03:51:17+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T03:51:17+0200
---

# Two elided-id links of a post-clear handoff do not resolve

Goal: investigate, verify and fix the root cause. Split from TRDD-JK2MLS8Z on 2026-10-10 (one atomic task per card); not investigated beyond what is written here. On the clear of 2026-10-10 03:04 the check handoff_links_resolve of scripts/handoff_clear_verify.py --phase after failed for the first time: 2 of 41 links, both elided ids of tool results of the cleared session 4487ea93 (ids beginning 82c23f01 and 5dda1f01; reports/continuity-build/20261010_030813+0200-handoff-clear-verify.md, gitignored). The previous clear resolved 41 of 41. To do: find whether the ids are absent from the transcript, or the resolver cannot address a line-range id or a tool-call id.

## Approval log

- 2026-10-10T03:51:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
