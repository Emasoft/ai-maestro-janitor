---
trdd-id: 5J3ITQXY
title: Secret-shield TS timing tests fail under host load and block the publish
column: todo
status: tasked
created: 2026-11-20T04:14:59+0100
updated: 2026-11-20T04:14:59+0100
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
approval-datetime: 2026-11-20T04:14:59+0100
---

# Secret-shield TS timing tests fail under host load and block the publish

Observed 2026-11-20 04:11 on the second publish.py --patch run (log reports_dev/main-agent/publish-20261120_041120+0100.txt, local): run_secret_shield_tests failed with 9 of 1365 bun tests, every one a timing assertion (ratio or wall-clock): clone addresses under 100 ms at 256 KB, redactJsonLine stability timed out at 5000 ms, 4000-line copy pass timed out, 4 ssh public key growth-ratio cases, the port-skip query scan ratio, and the URL password growth case. Host load average was about 52 on 14 cores at the time; the same suite passed on the first publish run 3 minutes earlier. Precedent: TRDD-KJAFABDU fixed the same class for the parallel-scoring test. Needed: each timing assertion measures cost in a way load cannot break (operation counts, a best-of-N minimum, or a ratio against a same-run baseline with a load-aware floor), so a real superlinear regression still fails while host load alone does not.

## Approval log

- 2026-11-20T04:14:59+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
