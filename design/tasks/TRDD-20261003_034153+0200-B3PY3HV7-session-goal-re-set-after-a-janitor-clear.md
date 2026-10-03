---
trdd-id: B3PY3HV7
title: Session goal re-set after a janitor clear
column: backburner
status: tasked
created: 2026-10-03T03:41:53+0200
updated: 2026-10-03T03:45:41+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:41:53+0200
project-id: ai-maestro-janitor
review-after: 2026-10-17
parent-trdd: K9AHY1ZB
derived: true
---

# Session goal re-set after a janitor clear

- **C4**: when an unmet goal existed, the chain types `/goal <sanitized>` **instead of** `/janitor-resume`.
  - It is one push and one turn, and it mirrors native compaction, which keeps the goal active. The goal's kickoff turn waits for the SessionStart context, which includes the Continuity block and NEXT ACTION.
  - The flag left by `/janitor-resume` is consumed by the next idle fire.
  - Sanitizer: no control characters or newlines, collapsed whitespace, at most 4,000 chars, no leading `/`, `[janitor-` defanged.
  - Check whether `user_intent.record_intent_from_prompt` (`lib/user_intent.py:191`) records a janitor-typed `/goal` as owner intent.
  - Tests: the keystroke plan for an unmet, met and absent goal; a sanitizer table.

Parent plan: TRDD-K9AHY1ZB

## Approval log

- 2026-10-03T03:41:53+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
