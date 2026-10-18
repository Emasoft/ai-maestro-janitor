---
trdd-id: B5CS1JC8
title: A full pytest run reported a plugin-data usage-probe file changed on disk
column: backburner
status: tasked
created: 2026-10-18T11:04:14+0200
updated: 2026-10-18T11:04:14+0200
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
approval-datetime: 2026-10-18T11:04:14+0200
---

# A full pytest run reported a plugin-data usage-probe file changed on disk

Seen 2026-10-18 by the worker running the full suite for TRDD-85NZX5RJ (report reports/board/20261018_105715+0200-85NZX5RJ-fix.md): pytest printed a notice that a usage-probe file in the plugin DATA dir changed during the run. Not traced. It may be the live daemon or a test writing to the real plugin DATA dir (the isolation hazard in the janitor-keepalive-test-isolation-fsevents memory page). TO DO FIRST: find the exact notice text and file, then which test or process wrote it.

## Approval log

- 2026-10-18T11:04:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
