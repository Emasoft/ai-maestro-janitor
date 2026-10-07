---
trdd-id: OEGPT048
title: The daemon keepalive error log is never rotated or capped
column: todo
status: tasked
created: 2026-10-07T04:44:45+0200
updated: 2026-10-07T05:15:50+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T04:44:45+0200
---

# The daemon keepalive error log is never rotated or capped

## Problem
The LaunchAgent sends the daemon's own stderr to daemon-keepalive.err.log in the janitor log dir (scripts/keepalive_install.sh, the StandardErrorPath line). Only files written through log_line are rotated (state.rotate_log_if_big), so this file grows without bound.

## Found while
Checking that the new 'assuming Claude is running' line of the rotator's running check also prints in the daemon process on the alert path, about once per stalled beat (10 in about 52 hours measured).

## Acceptance
- [ ] The file is rotated or capped like the other daemon logs, with a test.

## Approval log

- 2026-10-07T04:44:45+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

2026-10-07: not started. NEXT ACTION: add rotation or a cap for daemon-keepalive.err.log, test first.
2026-10-07 scoping (no code changed): launchd opens the StandardErrorPath file by path at job start (append mode inferred, not verified); a rename while the daemon runs leaves the process writing to the renamed file, and an in-place truncate works only if the descriptor is in append mode, otherwise it leaves a sparse hole. The file is 0 bytes on this host (last modified in June) and the growth described by this card was not reproduced; no code redirects the daemon's stderr, so anything the daemon prints to stderr lands there. Two options: (a) at start-up and over a cap of about 1 MiB, copy to a .1 file then truncate in place: small, no plist change, may lose lines written between copy and truncate, relies on append mode; (b) os.dup2 fd 2 onto a log in the janitor log dir rotated by the existing log_line/rotate_log_if_big: one mechanism, rename-safe, but touches start-up and needs a re-dup after rotation, and crashes before the redirect still go to the launchd file. Recommended: (a). Open point: verify the descriptor is in append mode. Test sketch: temp file over cap, open O_APPEND as a launchd stand-in, run the trim, assert size under cap, write through the same descriptor, assert the new bytes are at the start and there is no NUL hole.
