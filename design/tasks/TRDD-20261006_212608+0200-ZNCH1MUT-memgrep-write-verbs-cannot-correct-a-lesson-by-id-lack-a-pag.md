---
trdd-id: ZNCH1MUT
title: memgrep write verbs cannot correct a lesson by id, lack a page description verb and have an undocumented stdin contract
column: dev
status: tasked
created: 2026-10-06T21:26:08+0200
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
approval-datetime: 2026-10-06T21:26:08+0200
implementation-commits: [6eabe6b7, 15344f01, 6f45acf8]
---

# memgrep write verbs cannot correct a lesson by id, lack a page description verb and have an undocumented stdin contract

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

landed on main as 6eabe6b7,15344f01,6f45acf8; ships in the next release; issue stays open until then. Follow-ups for #331 still in progress.
NEXT ACTION: follow-up worker (worktree branch from main 6f45acf8, report under that worktree's reports/issue-sweep/) builds the leftover; merge, then release.
FOLLOW-UP LOCATION: worktree <repo>/.claude/worktrees/agent-a6a3620c9a8b90c72, branch worktree-agent-a6a3620c9a8b90c72; its report lands in that worktree's reports/issue-sweep/.

Source: GitHub issue Emasoft/ai-maestro-janitor#331 (opened 2026-10-05). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: Four gaps share one cause, the write verb contract. A lesson cannot be superseded under its own id, no verb sets a page description, the stdin behaviour is undocumented, and a repair shrinks the recall surface. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:26:08+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.




