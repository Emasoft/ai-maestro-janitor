---
trdd-id: 2GRMR89F
title: On Linux an enabled runaway guard is a silent no-op
column: backburner
status: tasked
created: 2026-10-23T08:26:43+0200
updated: 2026-10-23T08:31:40+0200
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
approval-datetime: 2026-10-23T08:26:43+0200
---

# On Linux an enabled runaway guard is a silent no-op

Found by the review of df927d32 (3.8.12 ubuntu CI fix). The notifier half of the original card is now TRDD-F5IE9WYI (an EHT of TRDD-1J9B7MWO). ? INFERRED from reading the code, not measured: daemon.task_runaway_guard reads host pressure through runaway_guard.free_memory_mb (vm_stat) and runaway_guard.swapfile_size_bytes (the macOS swapfile layout); on Linux those return None and the chore appears to return before its process scan, so an ENABLED guard would do nothing and report nothing, against the fail-fast rule. First step: run it on a Linux host with the option enabled and record what it does. Fix: a Linux probe (/proc/meminfo, /proc/swaps) or a one-time explicit unsupported-platform report. Probably not a regression of 3.8.12 (? INFERRED, history not read). Related: TRDD-1J9B7MWO.

## Approval log

- 2026-10-23T08:26:43+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
