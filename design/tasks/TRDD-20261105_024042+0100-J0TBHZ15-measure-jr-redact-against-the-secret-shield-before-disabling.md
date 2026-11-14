---
trdd-id: J0TBHZ15
title: Measure jr-redact against the secret shield before disabling it
column: todo
status: tasked
created: 2026-11-05T02:40:42+0100
updated: 2026-11-14T01:14:45+0100
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
approval-datetime: 2026-11-05T02:40:42+0100
---

# Measure jr-redact against the secret shield before disabling it

Owner decision 2026-11-05 (quoted on TRDD-2V7OAUPE): jr-redact is measured before TRDD-2V7OAUPE disables it.
## Done when
 - [x] A report runs jr-redact and the secret shield on the same inputs (the shield test samples and the catalog oracle samples) and lists what each hides, with counts, plus runtime on a fixed 512 KB input.
 - [x] Everything jr-redact hides that the shield does not gets a card or a KNOWN-MISSES entry before jr-redact is disabled.

## Approval log

- 2026-11-05T02:40:42+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-14 — Done-when (1) met: worker report reports_dev/sonnet-worker/20261114_011329+0100-j0tbhz15-jr-redact-vs-shield.md (function level, shield suite 656/656 on a scratch copy). Tests set 931: both 68, shield only 568, jr only 5, neither 290. Catalog 4,932: both 416, shield only 330, jr only 75, neither 4,111. Runtime on a fixed 524,288-byte input, median of 9: jr 3.0 ms, shield 21.3 ms (secret-free); 2.7 vs 23.5 ms (64 secrets). Done-when (2) met: every jr-only family is on TRDD-6A3XW3VO.
