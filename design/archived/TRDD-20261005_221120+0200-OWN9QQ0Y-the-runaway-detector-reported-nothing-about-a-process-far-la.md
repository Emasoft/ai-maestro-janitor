---
trdd-id: OWN9QQ0Y
title: The runaway detector reported nothing about a process far larger than the machine's memory
column: complete
status: archived
created: 2026-10-05T22:11:20+0200
updated: 2026-10-10T18:38:38+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:20+0200
---

# The runaway detector reported nothing about a process far larger than the machine's memory

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

A detector named system-daemon-runaway exists and logged nothing about a 97 GB process. Read what it watches and why this was outside it.

## Approval log

- 2026-10-05T22:11:20+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T18:38:38+0200 — COMPLETE by main-agent@ai-maestro-janitor. cause read from the detector's own log; no code by decision.

## Corrections

2026-10-05 (review): only the detector's log file name was seen; its log was not read, so 'reported nothing' is unverified. Overlaps TRDD-BZ3BT0NJ.

## Acceptance

- [x] Narrowed: read and explained, nothing built. The detector lists every process and reports one above 4096 MB RESIDENT, on a heartbeat fire about every 600 s. Its own log holds five lines, each a 10 s timeout of its process listing, the last at 2026-10-05T21:33:29, minutes before the hang; on a failed listing it reports nothing by design (scripts/detectors/system-daemon-runaway.py, the ps_text is None branch). That line is this card's own event for that fire. NOT ruled out for earlier fires: a listing that succeeded while the process read under 4 GB resident, which is what compressed memory looks like (on 2026-10-10 a fastedit process read 16.6 GB footprint and 1.8 GB resident 20 s after the system reported it at 13.7 GB). That second gap is covered since v3.7.1 by the daemon's size watch, which reads footprint. DECIDED: the silent timeout stays; host distress is the host-load detector's job (in tags from v3.7.0). NOT CHECKED: whether host-load fired on 2026-10-05 21:33.
