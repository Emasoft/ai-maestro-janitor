---
trdd-id: Q6UOJR8G
title: Measure whether trddgrep run from a linked worktree finds the in-tree LOCAL design
column: backburner
status: tasked
created: 2026-10-23T22:57:14+0200
updated: 2026-10-23T22:57:14+0200
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
---

# Measure whether trddgrep run from a linked worktree finds the in-tree LOCAL design

Today's layout question split off from TRDD-M5BRPISQ (review of ca17df81). The in-tree .claude/local/design is gitignored, so a linked worktree has no copy of it. trddgrep walks up from the cwd realpath (spec F20, F12), and a worktree under .claude/worktrees/ might still reach the main checkout's folder. Measure read-only, with a scratch worktree, which LOCAL corpus trddgrep reports from inside it. Record the answer as a spec WL-FACT line and on TRDD-M5BRPISQ.

## Approval log

- 2026-10-23T22:57:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
