---
trdd-id: OEGPT048
title: The daemon keepalive error log is never rotated or capped
column: backburner
status: tasked
created: 2026-10-07T04:44:45+0200
updated: 2026-10-10T22:03:51+0200
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
review-after: 2027-01-10
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
- 2026-10-10T22:03:51+0200 — column → backburner by main-agent@ai-maestro-janitor. growth is real but about 1 MB over months; re-check 2027-01-10

## STATE

2026-10-07: not started. NEXT ACTION: add rotation or a cap for daemon-keepalive.err.log, test first.
2026-10-07 scoping (no code changed): launchd opens the StandardErrorPath file by path at job start (append mode inferred, not verified); a rename while the daemon runs leaves the process writing to the renamed file, and an in-place truncate works only if the descriptor is in append mode, otherwise it leaves a sparse hole. The file is 0 bytes on this host (last modified in June) and the growth described by this card was not reproduced; no code redirects the daemon's stderr, so anything the daemon prints to stderr lands there. Two options: (a) at start-up and over a cap of about 1 MiB, copy to a .1 file then truncate in place: small, no plist change, may lose lines written between copy and truncate, relies on append mode; (b) os.dup2 fd 2 onto a log in the janitor log dir rotated by the existing log_line/rotate_log_if_big: one mechanism, rename-safe, but touches start-up and needs a re-dup after rotation, and crashes before the redirect still go to the launchd file. Recommended: (a). Open point: verify the descriptor is in append mode. Test sketch: temp file over cap, open O_APPEND as a launchd stand-in, run the trim, assert size under cap, write through the same descriptor, assert the new bytes are at the start and there is no NUL hole.
2026-10-10 22:03 NOT BUILT, parked on measured facts (a worker was started on option (a) and stopped before it changed a file, after the review asked whether anyone has this problem). CORRECTION to the scoping line above: the file is not 0 bytes. There are two: the one in the retired janitor-global-state directory is 981522 bytes, last written 2026-10-09 20:55; the one in the canonical global-state directory under the plugin data dir is 613 bytes, last written 2026-10-10 16:37 (the daemon, pid 6931, is running under launchd and writes the canonical one now). So the growth is real and slow: about 1 MB over the months the legacy file lived, a few megabytes a year at that rate; its lines are useful diagnostics (slow keychain reads, the rotator's ps timeout). A start-up-only trim would rarely run on a daemon that lives for weeks, the append mode of launchd's descriptor is still unverified (the worker's lsof step did not run: it looked for a process named daemon.py and found none, the real command line goes through the keepalive wrapper), and a copy-then-truncate can lose lines. DECISION by the main session under the drain mandate: no code now; re-check the canonical file's size on the review date and build only if it has passed 5 MB. The legacy 981 KB file belongs to the retired directory and is left alone (outside the project tree).
