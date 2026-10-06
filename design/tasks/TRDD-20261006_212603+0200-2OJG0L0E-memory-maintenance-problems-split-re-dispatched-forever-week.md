---
trdd-id: 2OJG0L0E
title: Memory maintenance problems split re-dispatched forever, weekly verbatim re-arm, lint count spam, autorecall on notifications
column: dev
status: tasked
created: 2026-10-06T21:26:03+0200
updated: 2026-10-06T22:07:12+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:26:03+0200
implementation-commits: [6e95fb5e, ecb8cc7f, 9ad6b9f6, 16d832ef]
---

# Memory maintenance problems split re-dispatched forever, weekly verbatim re-arm, lint count spam, autorecall on notifications

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

landed on main as 6e95fb5e,ecb8cc7f,9ad6b9f6,16d832ef; ships in the next release; issue stays open until then. Follow-ups for #326 still in progress.
NEXT ACTION: follow-up worker (worktree branch from main 6f45acf8, report under that worktree's reports/issue-sweep/) builds the leftover; merge, then release.
FOLLOW-UP LOCATION: worktree <repo>/.claude/worktrees/agent-a6a3620c9a8b90c72, branch worktree-agent-a6a3620c9a8b90c72; its report lands in that worktree's reports/issue-sweep/.

Source: GitHub issue Emasoft/ai-maestro-janitor#326 (opened 2026-10-02). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: Four problems were seen. The split chore is re-dispatched about twice a day on a scope it can never act on, verbatim atoms re-arm weekly, a lint count spams the heartbeat, and auto-recall runs on task notifications. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:26:03+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.




