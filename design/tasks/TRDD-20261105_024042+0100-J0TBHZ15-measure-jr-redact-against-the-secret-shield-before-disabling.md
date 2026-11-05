---
trdd-id: J0TBHZ15
title: Measure jr-redact against the secret shield before disabling it
column: todo
status: tasked
created: 2026-11-05T02:40:42+0100
updated: 2026-11-05T02:41:34+0100
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
 - [ ] A report runs jr-redact and the secret shield on the same inputs (the shield test samples and the catalog oracle samples) and lists what each hides, with counts, plus runtime on a fixed 512 KB input.
 - [ ] Everything jr-redact hides that the shield does not gets a card or a KNOWN-MISSES entry before jr-redact is disabled.

## Approval log

- 2026-11-05T02:40:42+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
