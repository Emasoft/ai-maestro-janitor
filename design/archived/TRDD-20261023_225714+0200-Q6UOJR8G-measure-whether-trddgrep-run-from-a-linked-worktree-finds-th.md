---
trdd-id: Q6UOJR8G
title: Measure whether trddgrep run from a linked worktree finds the in-tree LOCAL design
column: complete
status: archived
created: 2026-10-23T22:57:14+0200
updated: 2026-10-23T23:53:44+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-23T22:57:14+0200
relevant-rules: [24, 26]
---

# Measure whether trddgrep run from a linked worktree finds the in-tree LOCAL design

Today's layout question split off from TRDD-M5BRPISQ (review of ca17df81). The in-tree .claude/local/design is gitignored, so a linked worktree has no copy of it. trddgrep walks up from the cwd realpath (spec F20, F12), and a worktree under .claude/worktrees/ might still reach the main checkout's folder. Measure in a scratch worktree (a git write: git worktree add, then remove it afterwards; nothing else is changed) and record which LOCAL corpus trddgrep reports from inside it. Record the answer as a spec WL-FACT line and on TRDD-M5BRPISQ.

## Approval log

- 2026-10-23T22:57:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-23T22:58:23+0200 — column → todo by main-agent@ai-maestro-janitor. cheap, unblocked measurement of a present-day gap; backburner would hide it (review of 03ef8b7a)
- 2026-10-23T23:53:44+0200 — COMPLETE by main-agent@ai-maestro-janitor. measured; spec F21.

## Acceptance criteria

- [x] Measured read-only, using an existing in-repo worktree instead of creating one: trddgrep reaches LOCAL design only through --design-dir, from the main checkout and from a linked worktree alike; recorded as spec F21 and on TRDD-M5BRPISQ. Worktrees outside the repo tree were not on disk and are not measured.
