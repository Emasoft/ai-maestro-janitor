---
trdd-id: J7UA9O75
title: post-clear-compact hook runs at up to 83 percent of its 90 s limit
column: backburner
status: tasked
created: 2026-10-17T04:12:18+0200
updated: 2026-10-17T04:12:18+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-17T04:12:18+0200
---

# post-clear-compact hook runs at up to 83 percent of its 90 s limit

Found while closing TRDD-14Q1GRAU. Since 2026-10-11 the SessionStart post-clear-compact hook (on-session-start-post-clear-compact.py, limit 90 s in hooks/hooks.json) shows n=132, p50 4160 ms, max 74726 ms, i.e. up to 83 percent of its limit. Why it matters: on /clear, a timeout cancels the hook and the fresh session loses the Jev compaction context. Trigger to act: any hook_cancelled record for that hook in the session transcripts (attachment.hookEvent SessionStart). Action then: measure the tail, raise the limit or shorten the hook, and extend tests/test_session_start_hook_timeout.py.

## Approval log

- 2026-10-17T04:12:18+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
