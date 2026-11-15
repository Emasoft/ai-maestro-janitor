---
trdd-id: ZANQ1QW0
title: Bound the env-secret-on-disk walk and read the newest change first, then schedule it
column: backburner
status: tasked
created: 2026-11-15T23:26:34+0100
updated: 2026-11-15T23:26:34+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-15T23:26:34+0100
---

# Bound the env-secret-on-disk walk and read the newest change first, then schedule it

Follow-up of TRDD-G14LKPEC (issue 354). env-secret-on-disk is on demand only; tests/test_env_secret_on_disk_registration.py pins it off the roster. Fix before scheduling it. (1) Bound the walk: the time and byte budget must also cover listing and stat (today started = clock() runs after the walk in env_secrets.sweep), for example stop the walk at the budget and resume from a saved position, or skip folders unchanged since the last pass. (2) Read new changes before the backlog, so a fresh leak is found on the next pass. Then add back the roster row, the cadence option, the doctor and fleet-status entries, the quiet-heartbeat security entry and the two README rows (patch kept at reports_dev/fanout-apply/scratch/inc2/step10-schedule.patch, gitignored), and flip the registration test. Measured numbers are in the TRDD-G14LKPEC Approval log.

## Approval log

- 2026-11-15T23:26:34+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
