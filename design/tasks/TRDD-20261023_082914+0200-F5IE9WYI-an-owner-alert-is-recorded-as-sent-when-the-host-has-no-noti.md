---
trdd-id: F5IE9WYI
title: An owner alert is recorded as sent when the host has no notifier backend
column: backburner
status: tasked
created: 2026-10-23T08:29:14+0200
updated: 2026-10-23T08:29:14+0200
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
approval-datetime: 2026-10-23T08:29:14+0200
---

# An owner alert is recorded as sent when the host has no notifier backend

VERIFIED by reading scripts/lib/notify.py at a1aee776: notify.notify_episode records the episode in notify-sent.txt BEFORE calling notify._deliver (deliberate, so a crash or failed delivery never becomes a repeat), then returns PUSHED unconditionally. notify._deliver picks osascript on darwin, else notify-send when shutil.which finds it, else nothing; tier 2 fires only if a webhook URL is set. So on a Linux host without notify-send and no webhook, and on every Windows host until TRDD-V5FP4506, an owner alert (rotator remediation, login needed, cookie refresh) is recorded as sent, never shown, never retried, and nothing records the loss. Since TRDD-1J9B7MWO removed the heartbeat channel for these alerts (owner ruling: they reach the user only through system notifications), such a host loses them silently, against the fail-fast rule. Fix direction: _deliver reports whether any backend fired; with none, notify_episode must not record the episode as sent and must leave a durable, visible trace (findings ledger record and a daemon log line naming the undelivered condition). Tests: a host with no notifier and no webhook yields no sent record and one undelivered trace; a real notify-send stub on PATH yields PUSHED. EHT of TRDD-1J9B7MWO.

## Approval log

- 2026-10-23T08:29:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
