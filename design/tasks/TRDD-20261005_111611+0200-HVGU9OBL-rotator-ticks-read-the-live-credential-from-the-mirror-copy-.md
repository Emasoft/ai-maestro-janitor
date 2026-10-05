---
trdd-id: HVGU9OBL
title: rotator ticks read the live credential from the mirror copy because the primary is unreadable
column: todo
status: tasked
created: 2026-10-05T11:16:11+0200
updated: 2026-10-05T11:16:11+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T11:16:11+0200
---

# rotator ticks read the live credential from the mirror copy because the primary is unreadable

Found on 2026-10-05 while checking live events: in the rotator log that existed on one host, every tick ran with the primary live credential unreadable and used the mirror copy, and about a third of the ticks logged the accounts as exhausted with none usable. Not investigated. Machine detail (counts, times) is kept out of this card on purpose.

It may be one cause behind four symptoms carded separately: the rotation-stuck alert (TRDD-3OS6AXV3), abnormal ticks with keychain lookup timeouts (TRDD-HSRERK5S), ticks of 30 seconds or more (TRDD-JY0OBQZ4), and the unobservable live-account usage line (TRDD-G9Z8PXCM). That link is a hypothesis: each could also have its own cause.

First step, read-only: find in the rotator why the primary read fails headless (the keychain access the daemon has, the owner step on the mirror item that TRDD-G9Z8PXCM waits for) and whether the mirror path is the designed fallback or a degraded mode.

## Approval log

- 2026-10-05T11:16:11+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
