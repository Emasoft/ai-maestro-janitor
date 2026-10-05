---
trdd-id: 1HKQ4KQV
title: The rotator log may print a 429 streak count from a variable the alternates loop overwrites
column: todo
status: tasked
created: 2026-10-05T22:08:49+0200
updated: 2026-10-05T22:08:49+0200
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
