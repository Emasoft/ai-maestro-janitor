---
trdd-id: F5IE9WYI
title: An owner alert is recorded as sent when the host has no notifier backend
column: todo
status: tasked
created: 2026-10-23T08:29:14+0200
updated: 2026-10-23T08:33:01+0200
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

VERIFIED by reading scripts/lib/notify.py at a1aee776: notify.notify_episode records the episode in notify-sent.txt BEFORE calling notify._deliver (deliberate, so a crash or failed delivery never becomes a repeat), then returns PUSHED unconditionally. notify._deliver picks osascript on darwin, else notify-send when shutil.which finds it, else nothing; tier 2 fires only if a webhook URL is set. So on a Linux host without notify-send and no webhook (Windows has no backend either, but that is tracked by TRDD-V5FP4506), an owner alert (rotator remediation, login needed, cookie refresh) is recorded as sent, never shown and never retried, and the daemon log line "notify-episode: sent" positively claims a delivery that did not happen. Since TRDD-1J9B7MWO removed the heartbeat channel for these alerts (owner ruling: they reach the user only through system notifications), such a host loses them silently, against the fail-fast rule. Requirements (the mechanism is proposed and reviewed when the card is pulled, not fixed here): (1) keep record-before-deliver, so a crash or failed delivery never becomes a repeat; do not make the record wait on delivery, which would re-notify after a crash and emit a trace every pass. (2) An alert no backend could show is never recorded or logged as "sent"; it leaves exactly ONE durable, queryable trace per episode (findings ledger), not one per pass. (3) An observed clear_episode for the same condition, kind and slot also ends that undeliverable state, so a recurrence after the flap window leaves a new trace. (4) Decide, and say which: a backend that is present but fails (notify-send found with no D-Bus session, the usual case for a background daemon; osascript with notifications disabled) either counts as undelivered via the runner exit status, or is an accepted, documented limit. (5) OWNER QUESTION, unresolved: does a user-configured webhook count as delivery for an owner alert, given the ruling that these alerts reach the user only through system notifications? Tests: no notifier and no webhook gives no sent record and exactly one trace across repeated passes; clear, then recurrence after the flap window, gives a second trace; a real notify-send stub on PATH gives PUSHED. EHT of TRDD-1J9B7MWO.

## Approval log

- 2026-10-23T08:29:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
