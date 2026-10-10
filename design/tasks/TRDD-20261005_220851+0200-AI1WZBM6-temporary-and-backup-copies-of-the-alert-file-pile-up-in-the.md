---
trdd-id: AI1WZBM6
title: Temporary and backup copies of the alert file pile up in the rotator directory and a week-old alert is still listed
column: human_review
status: tasked
created: 2026-10-05T22:08:51+0200
updated: 2026-10-10T15:32:48+0200
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

## Findings

2026-10-10 15:32, wave 10 card 3, measured by the main session, no code. WHICH WRITER: no file under this repository's scripts names active-alerts; the file, its temporary copies and its dated backups are written by the ai-maestro server (lib/json-io.ts builds both names, path.tmp.pid.n and path.aim-bak-stamp-pid-counter; lib/oauth-rotator/alert-delivery.ts and tick.ts use it). The janitor only shares the directory. ON DISK today in the rotator data directory: 8 temporary copies, seven dated 2026-08-02 and one 2026-08-07, four of them empty; 10 backups, all of 2026-09-29 between 13:16 and 14:54; the active file itself last written 2026-09-29 14:54 with one entry, pinning-env, seen 450 times. So nothing has been added for eleven days: the temporary copies are leftovers of writes that died in August, and the backups stop at ten (json-io.ts lists the backups by prefix next to where it names them; that it prunes to ten is inferred from the count, the pruning code was not read). The week-old alert is listed because its writer has not written the file since; no janitor code reads it. To-do items: writer found (answered); cleanup and the rule for when an unseen alert leaves the list belong to the ai-maestro project and are NOT built here (its tree is not edited from this session); removing the 8 leftover temporary copies is a deletion outside this project's tree and is left to the owner. DRAFT for an issue on the ai-maestro repository, not sent: 'json-io atomic writes leave path.tmp.pid.n files behind when the process dies mid-write (8 found next to active-alerts.json, from 2026-08-02 and 08-07); active-alerts.json keeps an entry whose lastSeenAt is eleven days old. Requests: sweep temporary copies older than a day on start; drop an alert not seen for N hours.'
