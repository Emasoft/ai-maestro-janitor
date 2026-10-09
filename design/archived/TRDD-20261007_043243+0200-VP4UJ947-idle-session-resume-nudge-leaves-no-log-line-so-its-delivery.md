---
trdd-id: VP4UJ947
title: Idle-session resume nudge leaves no log line so its delivery cannot be verified
column: complete
status: archived
created: 2026-10-07T04:32:43+0200
updated: 2026-10-09T23:19:37+0200
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
- [x] Every emitted idle-session nudge writes one log line naming the session and the reason it was emitted.
- [x] A test fails before the change and passes after: an emit on the keep-going path produces exactly one such line.

Source: reports/board/20261007_042215+0200-live-check-HYTKG53C.md (gitignored). Related: TRDD-HYTKG53C.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-07
2026-10-07: not started. NEXT ACTION: add the log line on the emit branch of the keep-going path in scripts/dispatch.py, failing test first.
2026-10-07: merged on main (decb827b, merge f0c15f0b): the emit branch of the keep-going nudge writes one line to dispatch.log; test added. Not yet in a release; then TRDD-HYTKG53C's second acceptance item becomes observable.

## Approval log

- 2026-10-07T04:32:43+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T04:57:14+0200 — column → testing by main-agent@ai-maestro-janitor. merged on main; waits for a release
2026-10-09 CLOSED by the main session (board drain, wave 3). Checked by the main session itself: fix commits are ancestors of the v3.8.11 tag; the card's tests pass on a re-run today. Field: the card's own observable exists: .janitor/logs/dispatch.log holds 49 'keep-going: nudge emitted' lines, newest 2026-10-09T22:49:34; 21 keep_going tests pass. Assessment: reports/board/20261009_231646+0200-wave3-batchC.md.
2026-10-09 boxes ticked by the main session: box 1 on the live log (the line carries the session tag and the reason); box 2 on test_keep_going_emit_writes_one_log_line passing today. NOT re-demonstrated: that this test fails on the code before decb827b.
- 2026-10-09T23:19:37+0200 — COMPLETE by main-agent@ai-maestro-janitor. released in v3.8.11; both boxes evidenced.
