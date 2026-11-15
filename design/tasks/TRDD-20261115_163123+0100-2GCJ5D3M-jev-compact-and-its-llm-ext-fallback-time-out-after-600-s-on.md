---
trdd-id: 2GCJ5D3M
title: jev_compact and its llm-ext fallback time out after 600 s on every janitor clear so no compacted context lands
column: todo
status: tasked
created: 2026-11-15T16:31:23+0100
updated: 2026-11-15T16:42:44+0100
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

## Investigation

2026-11-15T16:45+0100 READ-ONLY INVESTIGATION (sonnet worker, local report reports_dev/sonnet-worker/20261115_164049+0100-2gcj5d3m-jev-timeout.md, gitignored; claims below are the worker's, not main-verified). CORRECTS the title premise, likely: on all six clears the hold-to-'both failed' interval is 602-611 s while the llm-ext fallback has a 600 s limit computed once before Jev runs, so Jev itself most likely fails within ~2-11 s (? INFERRED, timing arithmetic; Jev logs nothing of its own) and only the llm-ext fallback reaches 600 s. Both paths depend on llm-externalizer (jev_compaction.py:1171 scores via 'llm-ext classify filter'), so they are not independent. Leads: (1) jev-probe.json at 16:29:56 (after the six clears) records 'llm-ext: Path traversal blocked: /var/folders/.../items.jsonl resolves outside allowed directories', i.e. Jev's temp file sits outside llm-ext's allowed roots; (2) jev-auth-finding-seen touched 14:12:40, 3 s after the 14:12:37 hold start; (3) from ~/.llm-externalizer/history.log (read outside the brief, tagged as such): successful llm-ext session summaries took 236-588 s and 8 runs hit 600 s, so 600 s sits inside llm-ext's normal range. Host load: unassessable (host-load.log records only threshold crossings). NEXT CHECKS (no model call first): log Jev's exit code, stamp kind and stderr after each attempt; then re-run compact by hand with the temp dir inside llm-ext's allowed roots, and time one llm-ext session summary on the 14:12 transcript.
