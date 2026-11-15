---
trdd-id: 2GCJ5D3M
title: jev_compact and its llm-ext fallback time out after 600 s on every janitor clear so no compacted context lands
column: todo
status: tasked
created: 2026-11-15T16:31:23+0100
updated: 2026-11-15T16:31:23+0100
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
approval-datetime: 2026-11-15T16:31:23+0100
---

# jev_compact and its llm-ext fallback time out after 600 s on every janitor clear so no compacted context lands

MEASURED 2026-11-15 (main agent, read from .janitor/logs/session-summary.log, not run): on all 6 logged clears today (03:34, 07:22, 08:42, 09:31, 10:15, 14:12; the 05:23 and 12:03 holds left no outcome line) the post-clear summary logged 'jev and the llm-ext fallback both failed (transient: timed out after 600s) — template handoff written (it ends the hold)'. So the fresh session only gets the template handoff, never the Jev-compacted context; this bears on the owner complaint that clears do not restore the goals (TRDD-8ZY3JU2H) and on TRDD-5ID9CQY8's summary-hold timing. TO DO FIRST: read why both paths reach 600 s (jev_compact.py, the llm-ext call, host load at those times), reproduce one run by hand with timing; then fix the cause, not the timeout. Acceptance: a clear on this host lands a Jev-compacted context, shown by a session-summary.log success line, and a test pinning the failure mode found.

## Approval log

- 2026-11-15T16:31:23+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
