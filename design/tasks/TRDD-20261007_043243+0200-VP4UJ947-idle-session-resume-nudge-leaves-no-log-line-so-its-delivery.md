---
trdd-id: VP4UJ947
title: Idle-session resume nudge leaves no log line so its delivery cannot be verified
column: backburner
status: tasked
created: 2026-10-07T04:32:43+0200
updated: 2026-10-07T04:32:43+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T04:32:43+0200
---

# Idle-session resume nudge leaves no log line so its delivery cannot be verified

## Problem
The idle-session resume nudge (the [janitor-resume] cue the quiet heartbeat emits to a session that sits idle, TRDD-HYTKG53C) is emitted without writing any log line. In installed 3.8.2 scripts/dispatch.py the keep-going gate logs only through four log_line calls (lines 3928, 3948, 3954, 3960: the suppressed and unchanged cases); the emit branch goes through `_emit_decision("[janitor-resume]", ...)` and logs nothing.

## Why it matters
TRDD-HYTKG53C second acceptance item (an idle session receives [janitor-resume] within two fires) cannot be confirmed from dispatch.log: delivery is unobservable there and has to be inferred from the receiving session transcript. No nudge has ever been logged anywhere, so absence of a line proves nothing either way.

## Acceptance
- [ ] Every emitted idle-session nudge writes one log line naming the session and the reason it was emitted.
- [ ] A test fails before the change and passes after: an emit on the keep-going path produces exactly one such line.

Source: reports/board/20261007_042215+0200-live-check-HYTKG53C.md (gitignored). Related: TRDD-HYTKG53C.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-07
2026-10-07: not started. NEXT ACTION: add the log line on the emit branch of the keep-going path in scripts/dispatch.py, failing test first.

## Approval log

- 2026-10-07T04:32:43+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
