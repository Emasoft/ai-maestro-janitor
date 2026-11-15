---
trdd-id: IEY3JJJ0
title: Cost reports omit the advisor's own token spend
column: backburner
status: tasked
created: 2026-11-15T06:22:36+0100
updated: 2026-11-15T06:22:36+0100
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
approval-datetime: 2026-11-15T06:22:36+0100
---

# Cost reports omit the advisor's own token spend

2026-11-15 FOUND while fixing TRDD-8ZY3JU2H: when an assistant message contains an advisor call, the top-level usage block is the sum of the 'message' iterations only; the 'advisor_message' iteration (its own input and output tokens) appears in no top-level field. scripts/lib/token_history.py and scripts/token_report.py read only the top-level fields and never read usage.iterations, so advisor spend is missing from every cost report and burn figure. Verified on transcript 1603e47a entry at line 1105 (advisor input 398793, output 11231, absent from the top level). Fix direction: add the advisor_message iterations to the cost sums, priced at the advisor model's rate; check whether window-burn-rate and token_graph inherit the gap.

## Approval log

- 2026-11-15T06:22:36+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
