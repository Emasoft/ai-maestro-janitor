---
trdd-id: ZZHR41Y0
title: The heartbeat keeps reporting a long-silent background worker that was already stopped or died with the previous process
column: todo
status: tasked
created: 2026-11-19T12:34:09+0100
updated: 2026-11-19T12:34:15+0100
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
approval-datetime: 2026-11-19T12:34:09+0100
relevant-rules: [34]
---

# The heartbeat keeps reporting a long-silent background worker that was already stopped or died with the previous process

## Symptom (by the orchestrator, 2026-11-19, unverified unless stated)

- The heartbeat repeats "a background worker has been silent for 760 min with no running tool call" for a worker that was deliberately stopped (TaskStop) or died with the previous process.
- Hypothesis, not a fact: stopped agents stay in .janitor/state/pending-agents.json and keep being counted.
- Related: TRDD-PGN5XSHA (complete) fixed a deliberately killed subagent that stayed in the pending manifest; this may be a case it did not cover.

## Governing

PRRD G34.1.

## Done means

- [ ] Reproduced or shown absent, fixed with a test where one fits.

## Approval log

- 2026-11-19T12:34:09+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
