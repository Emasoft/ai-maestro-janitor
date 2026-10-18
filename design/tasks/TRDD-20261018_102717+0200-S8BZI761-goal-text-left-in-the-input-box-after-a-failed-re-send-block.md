---
trdd-id: S8BZI761
title: Goal text left in the input box after a failed re-send blocks every later janitor clear
column: todo
status: tasked
created: 2026-10-18T10:27:17+0200
updated: 2026-10-18T10:27:17+0200
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
approval-datetime: 2026-10-18T10:27:17+0200
---

# Goal text left in the input box after a failed re-send blocks every later janitor clear

Split from TRDD-85NZX5RJ on 2026-10-18 (review of 40171956). SYMPTOM, worker-read from .janitor/logs/clear-trigger.log (reports/board/20261018_102008+0200-85NZX5RJ-probe.md): after the 2026-10-13 14:41 goal re-send gave up (field not empty), the same goal tail was read in the input field at 17:40, 18:40 and 19:40 (session c436b9d9) and each later /clear was not sent: the unsent goal text stayed in the box and switched off the clear lever for over 5 hours. TO DO FIRST: read the log lines yourself, then the give-up path of the chain (TRDD-B3PY3HV7 owns the goal chain; terminal_trigger inject loop around scripts/lib/terminal_trigger.py:1119) and say whether a give-up leaves typed text behind and whether anything clears it. Any fix must never erase text the user typed. Acceptance: a give-up never leaves janitor-typed text in the field, shown by a test, or a recorded reason why it cannot be cleared safely.

## Approval log

- 2026-10-18T10:27:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
