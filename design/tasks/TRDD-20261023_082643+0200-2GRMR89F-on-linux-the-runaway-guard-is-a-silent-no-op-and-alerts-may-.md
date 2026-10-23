---
trdd-id: 2GRMR89F
title: On Linux the runaway guard is a silent no-op and alerts may be recorded as sent with no notifier
column: backburner
status: tasked
created: 2026-10-23T08:26:43+0200
updated: 2026-10-23T08:26:43+0200
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

# On Linux the runaway guard is a silent no-op and alerts may be recorded as sent with no notifier

Found by the review of df927d32 (3.8.12 ubuntu CI fix), INFERRED from reading the code, not yet measured. (1) daemon.task_runaway_guard reads host pressure with vm_stat and the macOS swapfile layout (scripts/lib/runaway_guard.py free_memory_mb ~773, swapfile_size_bytes ~1535); on Linux those return None and the chore returns before its process scan, so an ENABLED guard does nothing and reports nothing, against the fail-fast rule. Fix: a Linux probe (/proc/meminfo, /proc/swaps) or a one-time explicit unsupported-platform report. (2) scripts/lib/notify.py _deliver has no backend on a Linux host without notify-send (and none on Windows until TRDD-V5FP4506); check whether notify_episode still returns PUSHED and records the episode as sent, which would mark an owner alert delivered that was never shown, contradicting the owner ruling that these alerts reach the user only through system notifications. Related: TRDD-1J9B7MWO.

## Approval log

- 2026-10-23T08:26:43+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
