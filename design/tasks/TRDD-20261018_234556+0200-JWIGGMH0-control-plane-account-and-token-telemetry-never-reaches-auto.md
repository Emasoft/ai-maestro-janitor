---
trdd-id: JWIGGMH0
title: Control-plane account and token telemetry never reaches automatic agent context
column: testing
status: tasked
created: 2026-10-18T23:45:56+0200
updated: 2026-10-19T17:15:27+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-18T23:45:56+0200
---

# Control-plane account and token telemetry never reaches automatic agent context

Atomic routing fix referencing TRDD-6ESS2MGE. Account usage windows and percentages, token cost and budget, stale-spare reminders, all-accounts-maxed and rotation-capacity narration, and rate-limit explanatory prose are control-plane-only and must never enter any automatic agent-context surface. Explicit user-requested pull commands remain available.\n\n## Acceptance checklist\n\n- [ ] Forbidden telemetry is absent from heartbeat stdout, findings ledger and summaries, SessionStart injection, handoff payloads, and resume payloads.\n- [ ] Credential remediation remains owner-facing through a persistent owner-readable record plus notification, including capture-stalled when notification delivery fails or dedupes.\n- [ ] Rotation and model actuation behavior is unchanged.\n- [ ] Control-plane logs, state, dedupe, detector scheduling, notifications, and explicit pull diagnostics remain observable and unchanged except for the added capture-stalled owner record.\n- [ ] Rotator tick-stalled, credential-remediation, security, corruption, process-runaway, project-actionable findings, bare markers, and exact pending-task directives remain automatically visible where intended.\n- [ ] Focused positive and negative tests plus full pytest, ruff, mypy, and pyright pass.

## Approval log

- 2026-10-18T23:45:56+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-18T23:48:34+0200 — column → dev by main-agent@ai-maestro-janitor. Reviewed acceptance clarifications recorded; implementation authorized.

## Reviewed acceptance clarifications

- [ ] Audit inventory covers all automatic context emitters, and every relevant route uses the exclusion policy.
- [ ] Model-switch confirmed, unconfirmed, and failure outcomes stay durably owner-visible or agent-visible whenever task continuation depends on them.
- [ ] The owner-remediation record is dedicated control-plane state and is never fed to automatic agent context.
- [ ] Every side effect claimed unchanged has an explicit before-and-after assertion.

## STATE

- 2026-10-19T17:15:27+0200 — All acceptance checkboxes verified: 374 focused+full tests pass, ruff/mypy/pyright clean. Rotator-alert, model-fallback, oauth-login-needed, dispatch-phases, quiet-heartbeat tests updated; detectors wired into dispatch exclusion policy. Committed as feat commit on current branch (10 files, +414/-330). Ready for review/merge. Next: move to live_auditing after board drain verifies.
