---
trdd-id: AALVDWD0
title: The system log returned nothing for the minutes before the reboot
column: complete
status: archived
created: 2026-10-05T22:11:20+0200
updated: 2026-10-10T19:18:08+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:20+0200
---

# The system log returned nothing for the minutes before the reboot

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Three 'log show' queries for windows before the reboot of 2026-10-05 returned zero lines. Find whether the store does not persist that far or the queries were wrong, so the next investigation can use it.

## Approval log

- 2026-10-05T22:11:20+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T19:18:08+0200 — COMPLETE by main-agent@ai-maestro-janitor. measured: the store holds the window; query recipe on the card.

## Corrections

2026-10-05 (review): four queries returned nothing, not three (three by process id, one unfiltered). Same anomaly as the card on a hang leaving no evidence.

## Acceptance

- [x] Answered, measured by the main session on 2026-10-10 19:18: the store persists that far and the queries were at fault. Boot was 2026-10-05 21:43:09 (kern.boottime). 'log show --start "2026-10-05 21:MM:00" --end "2026-10-05 21:MM+1:00"' returns 5514 lines for 21:34, 6214 for 21:36, 10791 for 21:38, 16074 for 21:39, 2729 for 21:40, 894 for 21:41 and 1 (the header) for 21:42; the last entry is 21:41:32.48, 97 s before boot. The same form returns 7939 lines for 09:53 today. Recipe for the next investigation: explicit --start and --end in local time, one minute per query, no process-id filter (a process id does not survive a reboot). Also read: no kernel memory-pressure line in 21:30 to 21:41; the 55 lines matching jetsam, memorystatus, low swap or compressor are app-lifecycle messages. NOT CHECKED: why the four original queries returned nothing, their text is not kept; how far back the store reaches.
