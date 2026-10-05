---
trdd-id: QHACQPPG
title: The rotator reports a usage-endpoint throttle with no rotation target as exhausted and the stuck alert gives the wrong remedy
column: backburner
status: tasked
created: 2026-10-05T16:43:27+0200
updated: 2026-10-05T16:43:27+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T16:43:27+0200
---

# The rotator reports a usage-endpoint throttle with no rotation target as exhausted and the stuck alert gives the wrong remedy

The live-429 branch of cmd_auto sets near=True on a debounced usage-endpoint 429 and, when no target exists, logs "exhausted ... all paid accounts maxed" and writes the stuck marker even at 3% utilisation. scripts/lib/rotator_alert.py shows one fixed text ("run /janitor-capture-all-logins") for every marker kind, though a login capture cannot help kind all-accounts-maxed. Risk to weigh: silencing a true alert. Related: TRDD-YVC3F06V, TRDD-AWIWXJIG.

## Approval log

- 2026-10-05T16:43:27+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
