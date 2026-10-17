---
trdd-id: I40IKPWU
title: Handoff-clear verifier should check that each elided pointer expands
column: dev
status: tasked
created: 2026-10-17T01:38:05+0200
updated: 2026-10-17T03:37:00+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-17T01:38:05+0200
---

# Handoff-clear verifier should check that each elided pointer expands

Split from TRDD-AFW0CA65 (7b67bab6). After 7b67bab6, handoff_links_resolve skips Jev pointers ([[elided id=...]]) because they are expand handles, not wikilinks; on today's link-only handoffs that check reports SKIP. The only real recoverability test for elided content is that each pointer in the handoff resolves with `jev_compact.py expand --transcript <t> <id>`. To do: add a verifier check (before/after phase) that expands every pointer id against the cleared transcript and FAILs on any that does not resolve; measure on the existing handoffs first.

## Approval log

- 2026-10-17T01:38:05+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
