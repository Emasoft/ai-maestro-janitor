---
trdd-id: XOSC5AI5
title: Memory nudges reach no background memory chore
column: todo
status: tasked
created: 2026-10-10T04:55:24+0200
updated: 2026-10-10T04:55:24+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T04:55:24+0200
parent-trdd: 6ESS2MGE
---

# Memory nudges reach no background memory chore

Route 2 of the owner's routing rule of 2026-09-27 (quoted on TRDD-6ESS2MGE): a finding a background agent can fix becomes background work the main agent never sees. Worker-read 2026-10-10 (reports/board/20261010_044453+0200-6ess2mge-detector-table.md): memorize-nudge prints a drift line only; memory-librarian prints a drift line and writes a proposal file in the LOCAL memory dir; scripts/detectors/memory-maintenance.py, the only emitter of the janitor-memory chore markers, reads neither (its docstring says it never reads the corpus). So both findings reach only the main agent, as LOW ledger lines at session start. Unverified: whether a chore skill reads the librarian's proposal file. To do: read the chore skills for a consumer of that file; if none, decide whether the harvest or consolidate chore should take the nudge and the proposal as input, measured on this corpus before building; no new ticket kind without that measurement.

## Approval log

- 2026-10-10T04:55:24+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
