---
trdd-id: AI1WZBM6
title: Temporary and backup copies of the alert file pile up in the rotator directory and a week-old alert is still listed
column: todo
status: tasked
created: 2026-10-05T22:08:51+0200
updated: 2026-10-05T22:08:51+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:51+0200
---

# Temporary and backup copies of the alert file pile up in the rotator directory and a week-old alert is still listed

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed in the rotator's data directory: many files named active-alerts.json.tmp.<pid>.<n> and active-alerts.json.aim-bak-<date>, and an active-alerts.json whose only entry (a pinning environment variable warning) was last seen about a week earlier with a count of 450. To do: find which writer leaves the temporary files behind and which tool makes the dated backups, add cleanup, and decide when an alert that is no longer seen leaves the active list.

## Approval log

- 2026-10-05T22:08:51+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
