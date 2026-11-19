---
trdd-id: KUJQYBVF
title: The late-summary cue names another session's handoff and the external watcher keeps writing handoffs for a long-idle session with a wrong idle-hours header
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

# The late-summary cue names another session's handoff and the external watcher keeps writing handoffs for a long-idle session with a wrong idle-hours header

## Symptom (by the orchestrator, 2026-11-19, unverified unless stated)

- The late-summary cue gave session 5d861615 another session's summary: "a fuller summary of the cleared session is at .janitor/state/agent-handoff-e05195b8-20261118_211119+0100-79555.md -- read it FIRST: it supersedes the auto-composed template you resumed from, so reconcile your plan with it".
- Session e05195b8's transcript was last written 2026-11-16 08:57, yet the external watcher kept writing handoffs for it until 2026-11-18 21:11, and its header said "idle >= ~308h" (wrong: about 60 h).
- Code to read: scripts/dispatch.py around lines 2490-2525 (successor check, TRDD-W6DZPXLG).
- Related: TRDD-W6DZPXLG (complete), TRDD-1BF2XSHM, TRDD-XJI19HO7.

## Governing

PRRD G34.1.

## Done means

- [ ] Reproduced or shown absent, fixed with a test where one fits.

## Approval log

- 2026-11-19T12:34:09+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
