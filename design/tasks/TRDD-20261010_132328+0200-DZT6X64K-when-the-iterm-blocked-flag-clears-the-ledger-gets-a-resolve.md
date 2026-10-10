---
trdd-id: DZT6X64K
title: When the iTerm blocked flag clears the ledger gets a resolved entry so a replayed alert shows its resolution
column: todo
status: tasked
created: 2026-10-10T13:23:28+0200
updated: 2026-10-10T13:23:28+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T13:23:28+0200
---

# When the iTerm blocked flag clears the ledger gets a resolved entry so a replayed alert shows its resolution

## Approval log

- 2026-10-10T13:23:28+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Task

2026-10-10 13:23 Split from TRDD-0QCRG2YX (its remaining item 3, observed 2026-10-05): the session-start hook replays a project's unread ledger entries, so after the blocked flag cleared, every restarted session reported an iTerm alert whose condition was already gone. Wanted: when the flag clears, one ledger entry saying so, so the replay shows the alert together with its resolution; do not suppress the alert itself. Before building: read where the flag is removed (the fleet scan in the daemon, which writes into other projects' ledgers through findings_ledger.record with project_dir) and whether record() for a non-current project is the right path; one test with real files. No observed recurrence since 2026-10-05.
