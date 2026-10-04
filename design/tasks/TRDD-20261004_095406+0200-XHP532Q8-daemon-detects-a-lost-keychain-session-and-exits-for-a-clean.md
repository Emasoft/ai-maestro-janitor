---
trdd-id: XHP532Q8
title: Daemon detects a lost keychain session and exits for a clean respawn
column: design
status: tasked
created: 2026-10-04T09:54:06+0200
updated: 2026-10-04T09:54:11+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-04T09:54:06+0200
parent-trdd: JSQSJ3PZ
---

# Daemon detects a lost keychain session and exits for a clean respawn

OWNER DIRECTIVE 2026-10-04, verbatim: "don't make temporary things. implement permanent solutions."

Symptom. From 2026-10-04 09:03:04 every rotator tick logged only two lines, the cascade summary and "auto: no live credential", and none of the keepalive, repair or capture lines. Rotation, renewal and usage probing were all dead for about 50 minutes and nothing reported it. Three fresh slots captured by hand at 09:41 to 09:45 were not seen by the daemon.

Cause, strongly inferred. The macOS GUI login session was replaced at 09:02:39 (loginwindow and WindowServer restarted, no reboot). The daemon process started 2026-10-03 survived from the old session; from then on every keychain read it made returned nothing: the live item, its mirror and all slots. No denied-latch was set because the failures were quick and carried no denial text. A shell in the new session read all three slots normally. Stopping the old process let the launchd keepalive instance, already waiting for the singleton lock in the new session, take over.

Requirement. The daemon must notice that it has lost the keychain and recover without a human: when keychain reads that worked before start failing for every item across consecutive ticks while the items exist, it logs one clear line, raises the out-of-band rotator alert, and exits so the OS keepalive starts a fresh process in the current login session. It must not exit in a loop when the keychain is genuinely locked or denied (the existing denied-latch covers that case) and must not exit on a single slow read under load.

Open design points. How to tell a lost session from a locked or denied keychain without a secret read (the exact error text of the failing security call was not captured). Whether to compare the daemon's own login or audit session with the current console session. A minimum number of consecutive all-fail ticks. A cap on self-exits per hour. What a session-spawned daemon with no OS keepalive should do.

Verify. A test that simulates all keychain reads returning nothing for N consecutive ticks after earlier success and asserts the alert and the exit; a test that a single failure or a denied-latch does not trigger it; then a field observation after a release.

## Approval log

- 2026-10-04T09:54:06+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
