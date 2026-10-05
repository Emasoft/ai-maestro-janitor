---
trdd-id: HVGU9OBL
title: rotator ticks read the live credential from the mirror copy because the primary is unreadable
column: cancelled
status: archived
created: 2026-10-05T11:16:11+0200
updated: 2026-10-05T15:14:19+0200
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
- 2026-10-05T15:14:19+0200 — CANCELLED by main-agent@ai-maestro-janitor. explained: designed behaviour since 2b18348f, see TRDD-QQ7QCS3T.

## STATE

2026-10-05 — correction: the clause in the first paragraph about how many ticks logged the accounts as exhausted is account state of one host on one day and should not have been written here; treat it as removed. The finding is only that the primary live credential was unreadable to the daemon and the mirror copy was used.
2026-10-05 — the first step is reading the code and the logs ONLY. No keychain command is to be run: any query against the real item can raise a prompt on the owner's screen. Any fix that changes keychain access is the owner's decision.
2026-10-05 — RESOLVED AS EXPLAINED, not a defect. Read in the code by a worker and re-read by the main agent: the daemon marks its rotator tick as headless unless the daemon's own environment opts in to the primary read (scripts/daemon.py, the rotator-tick task), and a headless tick skips the read of the primary live item on purpose (scripts/oauth_rotator/rotator.py, the function that says whether the primary secret read is permitted): a headless process could only raise a prompt nobody can answer, so the code goes straight to the mirror copy. That is the default-off behaviour shipped in 2b18348f and waiting on the owner on TRDD-QQ7QCS3T. The title of this card describes designed behaviour.
2026-10-05 — what stays true and is NOT explained by this: the log line the automatic tick prints carries no reason, so that line alone cannot tell a designed skip from a failed read (the capture line does name the reason); and the rotation-stuck alert is separate — 'exhausted, none usable' is a measured usage verdict, not a consequence of the mirror path. Which condition raised the alert on 2026-10-05 was not found in the logs read. The four-symptom link in the body above is withdrawn.
