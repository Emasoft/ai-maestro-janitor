---
trdd-id: 45ZUV5ZD
title: A rotator tick exited with status 1 at 20h45 and nothing says why
column: testing
status: tasked
created: 2026-10-05T22:08:59+0200
updated: 2026-10-07T09:35:18+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:59+0200
implementation-commits: [01c663e6, b175178f]
---

# A rotator tick exited with status 1 at 20h45 and nothing says why

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed in the daemon log during a memory spike, at 20h45: the rotator tick command 'exited 1 (attempt 1 of N)' and the task then finished in 52 s. No reason was logged at the daemon level and the rotator log was not checked for that minute. To do: read both logs for that tick, find the failing step, and make the daemon line carry the reason.

## Approval log

- 2026-10-05T22:08:59+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T08:45:09+0200 — column → testing by main-agent@ai-maestro-janitor. B7 merged and gated at b175178f

## Implementation notes

2026-10-07: cause of the original failure unprovable (no daemon log from that day); only the retry log line improved: it now carries the failed attempt's masked stderr tail.
2026-10-07: shipped in v3.8.5; release observation starts.
