---
trdd-id: HF7GNHNF
title: URL_PASSWORD slows by a large step between 96 KB and 128 KB of URL-shaped text
column: todo
status: tasked
created: 2026-11-05T02:40:38+0100
updated: 2026-11-05T02:41:33+0100
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
approval-datetime: 2026-11-05T02:40:38+0100
---

# URL_PASSWORD slows by a large step between 96 KB and 128 KB of URL-shaped text

Owner decision 2026-11-05 (quoted on TRDD-2V7OAUPE): measure and fix this here, no upstream report. Measured 2026-11-04 under claude plugin test (TRDD-OD5Z90YL, Known before starting): redact() on the grown() shape b of tests/patterns.test.ts takes about 3 ms at 96 KB, 75 ms at 128 KB, 188 ms at 256 KB and 615 ms at 512 KB (load about 67); the password stays hidden at every size up to 1 MB. A diagnosis run started 2026-11-05 (report in reports_dev/sonnet-worker, name ends -urlpw-diagnosis.md). TRDD-OD5Z90YL stays the ReDoS harness; this card is the fix.
## Done when
 - [ ] The cause is named with a measurement that rules out the alternatives.
 - [ ] A test fails on the current URL_PASSWORD and passes after the fix.
 - [ ] On the grown() shapes, redact() meets the ratio rule of TRDD-Q6LPJTPO (under 12 across an 8x size step, or under 2 ms at the larger size) up to 512 KB, and the password stays hidden at every measured size.

## Approval log

- 2026-11-05T02:40:38+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
