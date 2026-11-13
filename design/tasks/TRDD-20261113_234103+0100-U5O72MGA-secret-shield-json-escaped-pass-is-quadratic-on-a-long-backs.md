---
trdd-id: U5O72MGA
title: Secret shield JSON_ESCAPED pass is quadratic on a long backslash run
column: todo
status: tasked
created: 2026-11-13T23:41:03+0100
updated: 2026-11-13T23:41:03+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-13T23:41:03+0100
---

# Secret shield JSON_ESCAPED pass is quadratic on a long backslash run

Measured 2026-11-13 in the plugin engine (claude plugin test, scratch copy; raw data reports_dev/sonnet-worker/20261113_233837+0100-agoewf2e-json-bound.md, not tracked): the JSON_ESCAPED pass of hooks/secret-shield/patterns.ts, whose pattern starts with a backslash run before a quote, is quadratic on a long run of backslashes. 108,326 backslashes take 5.1 s in redact() alone, the same before and after the AGOEWF2E change (5,077 ms new, 5,182 ms old); a secret-named or plain value followed by 54,152 escaped-backslash pairs takes 4.5 s. Quadratic growth puts about 150K backslashes near the 10 s hook limit. Open question that decides severity: when the secret-shield hook times out, does the tool result reach the model unredacted (fail open) or is it withheld (fail closed)? Done when: (1) the timeout behaviour of the shield hook is measured and written down; (2) JSON_ESCAPED is linear on a backslash run (a test with 1 MB of backslashes under a stated time, red on the old rule), or redact() withholds a text it cannot finish in time, shown by a test; (3) TRDD-2V7OAUPE is unblocked only after (1) and (2).

## Approval log

- 2026-11-13T23:41:03+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
