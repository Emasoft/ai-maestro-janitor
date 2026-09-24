---
trdd-id: 4P4Y2KBR
title: A clear injected a stale model-authored handoff from another session instead of a summary of the cleared session
column: todo
created: 2026-09-24T11:21:17+0200
updated: 2026-09-24T11:21:17+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T11:21:17+0200
---

# A clear injected a stale model-authored handoff from another session instead of a summary of the cleared session

Seen at the start of the session that followed the 2026-09-24 morning clear, on the INSTALLED v3.5.7 (no Jev code). The SessionStart injection was agent-handoff 3df0142c, written 2026-09-23 22:56 about a security review, while the session actually cleared was b2bf5b7b (the rotation incident, TRDD-K0PMVRN6). A resumed session was told the wrong story. Find which path chose that handoff (key match, newest-group selection, age limit) and whether the Jev lane on HEAD can make the same choice. Acceptance: a test where an older session's handoff exists and a different session is cleared, and the injection names the cleared session or none.

## Approval log

- 2026-09-24T11:21:17+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
