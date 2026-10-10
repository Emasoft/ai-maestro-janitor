---
trdd-id: 1HKQ4KQV
title: The rotator log may print a 429 streak count from a variable the alternates loop overwrites
column: complete
status: archived
created: 2026-10-05T22:08:49+0200
updated: 2026-10-10T15:00:08+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:49+0200
---

# The rotator log may print a 429 streak count from a variable the alternates loop overwrites

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Reported by a measurement worker reading cmd_auto, not verified by the main session: the name streak is reused by the loop over the alternates, so on the path to the stuck branch it no longer holds the live account's streak. To do: read the function, confirm or refute, and check every later use of the name (log text, decisions).

## Approval log

- 2026-10-05T22:08:49+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T15:00:08+0200 — COMPLETE by main-agent@ai-maestro-janitor. archived → complete.

## Decision

2026-10-10 15:00, wave 9 card 2: REFUTED by the main session, no code. In scripts/oauth_rotator/rotator.py the live account's count is formatted into live_desc before the loop over the alternates reuses the name streak, the stuck branch prints live_desc and the alternates' verdicts, and a search of the whole file for the bare name finds no read after the loop's last use. So no log line prints a wrong count. The reuse of one name for two counts remains a hazard for a later edit; it is not renamed here (no wrong output, and a rename is a change with no test to pin it).

## Acceptance

- [x] The function is read and the claim is refuted; every later use of the name is checked (there is none).
