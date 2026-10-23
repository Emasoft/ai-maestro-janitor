---
trdd-id: F5IE9WYI
title: An owner alert is recorded as sent when the host has no notifier backend
column: todo
status: tasked
created: 2026-10-23T08:29:14+0200
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
approval-datetime: 2026-10-23T08:29:14+0200
---

# An owner alert is recorded as sent when the host has no notifier backend

VERIFIED by reading scripts/lib/notify.py at a1aee776: notify.notify_episode records the episode in notify-sent.txt BEFORE calling notify._deliver (deliberate, so a crash or failed delivery never becomes a repeat), then returns PUSHED unconditionally. notify._deliver picks osascript on darwin, else notify-send when shutil.which finds it, else nothing; tier 2 fires only if a webhook URL is set. So on a Linux host without notify-send and no webhook (Windows has no backend either, but that is tracked by TRDD-V5FP4506), an owner alert (rotator remediation, login needed, cookie refresh) is recorded as sent, never shown and never retried, and the daemon log line "notify-episode: sent" positively claims a delivery that did not happen. Since TRDD-1J9B7MWO removed the heartbeat channel for these alerts (owner ruling: they reach the user only through system notifications), such a host loses them silently, against the fail-fast rule. Fix direction (keep record-before-deliver, which stops a crash or failed delivery from becoming a repeat): a backend_available() precheck (darwin, notify-send found, or a webhook URL set) runs BEFORE the episode decision. When it is true, behaviour is unchanged. When it is false, record a separate deduplicated undeliverable episode under its own key with the same flap logic, emit ONE durable visible trace per episode (a findings-ledger record naming the condition), and never log "sent". Making the record wait on delivery would re-notify after a crash and spam a trace every pass. Tests: a host with no notifier and no webhook yields no sent record and exactly one undeliverable trace across repeated passes; a real notify-send stub on PATH yields PUSHED. EHT of TRDD-1J9B7MWO.

## Approval log

- 2026-10-23T08:29:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
