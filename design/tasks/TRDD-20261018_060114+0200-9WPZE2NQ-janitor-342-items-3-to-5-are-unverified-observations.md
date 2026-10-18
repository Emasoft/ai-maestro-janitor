---
trdd-id: 9WPZE2NQ
title: janitor#342 items 3 to 5 are unverified observations
column: verify_assumptions
status: tasked
created: 2026-10-18T06:01:14+0200
updated: 2026-10-18T06:01:14+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-18T06:01:14+0200
parent-trdd: FQVEILVK
---

# janitor#342 items 3 to 5 are unverified observations

Source: janitor#342 items 3 to 5. The reporter states no source investigation was done. No code was read for these.

- Item 3, worker liveness presented as task progress: UNVERIFIED (conceptual/design item).
- Item 4, re-arm / duplicate-launch protocol: UNVERIFIED; the reporter attributes it to assistant misuse, not clearly a janitor defect.
- Item 5, hook timeouts (5733ms/5000ms), recall on notifications, `~0k` token advisory: recall on task notifications is already fixed (ecb8cc7f, #326, v3.8.0); the timeouts and the advisory are UNVERIFIED.

## Acceptance
- [ ] Each item is reproduced or refuted with file:line or a command result
- [ ] Confirmed items get their own bugfix card; refuted ones are reported on the issue by the owner

## Approval log

- 2026-10-18T06:01:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
