---
trdd-id: JOXQQL4J
title: The rotator alert evaluation fails when ps is slow and a load stall is reported as a stopped rotator
column: todo
status: tasked
created: 2026-10-05T22:08:50+0200
updated: 2026-10-05T22:08:50+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:50+0200
---

# The rotator alert evaluation fails when ps is slow and a load stall is reported as a stopped rotator

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed under very high load: the daemon logged 'rotator-alert: evaluation failed: Command ps -eo args= timed out after 10 seconds', one rotator tick took 717 s, and the next heartbeat showed 'the account rotator has stopped ticking - run /janitor-doctor' although the rotator ticked normally a minute later. To do: decide what the alert evaluation does when ps is slow (the evaluation is lost exactly when the host is in trouble), and whether a single late tick under load deserves the doctor remedy. Related: TRDD-JY0OBQZ4.

## Approval log

- 2026-10-05T22:08:50+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
