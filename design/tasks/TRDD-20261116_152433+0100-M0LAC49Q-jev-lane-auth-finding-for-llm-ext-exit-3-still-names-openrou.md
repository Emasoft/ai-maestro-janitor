---
trdd-id: M0LAC49Q
title: Jev lane auth finding for llm-ext exit 3 still names OPENROUTER_API_KEY in its remedy
column: backburner
status: tasked
created: 2026-11-16T15:24:33+0100
updated: 2026-11-16T15:44:30+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-16T15:44:27+0100
---

# Jev lane auth finding for llm-ext exit 3 still names OPENROUTER_API_KEY in its remedy

Follow-up of TRDD-7XDBJZCZ. Its Investigation entry (2026-11-15T17:56+0100) says the lane's auth finding for llm-ext exit 3 embeds llm-ext's message, but its remedy line still names OPENROUTER_API_KEY.

## Acceptance checklist
- [ ] the remedy line names the credential llm-ext actually needs, with a test

## Approval log
- 2026-11-16T15:44:27+0100 — APPROVED by main-agent@ai-maestro-janitor (min-approval-requirement: none). simple bugfix follow-up of TRDD-7XDBJZCZ; main agent approves.
- 2026-11-16T15:44:30+0100 — column → backburner by main-agent@ai-maestro-janitor.
