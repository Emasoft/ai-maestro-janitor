---
trdd-id: 8KGP78JN
title: memgrep recall prints a stale description after update-mem-topic because the index is not refreshed
column: backburner
created: 2026-09-24T13:29:36+0200
updated: 2026-09-24T13:29:36+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T13:29:36+0200
---

# memgrep recall prints a stale description after update-mem-topic because the index is not refreshed

Reported by the AgentlensPro Claude session (cross-session message, 2026-09-24 ~12:48), the second finding of the same report as TRDD-23QM8H5F: after three truncated atom descriptions were repaired with `memgrep update-mem-topic`, `memgrep recall <ATOM-id>` still printed the old truncated desc while the page files themselves were correct. The reporter's reading, not verified here: the SQLite index is not refreshed after that write verb. Since desc is the only field recall ranks on, a stale index serves the pre-repair text and ranking until something else reindexes. Evidence: in the AgentlensPro repo, reports/janitor-memory-subconscious-agent/20260924_122845+0200-split-project.md and the git diff of the three repaired pages. Acceptance: a test where update-mem-topic changes a desc and the very next recall prints the new desc, failing without the fix; check whether every memgrep write verb refreshes the index, not only this one.

## Approval log

- 2026-09-24T13:29:36+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
