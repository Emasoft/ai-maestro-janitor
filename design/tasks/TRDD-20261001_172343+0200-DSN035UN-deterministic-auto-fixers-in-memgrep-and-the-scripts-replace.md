---
trdd-id: DSN035UN
title: Deterministic auto-fixers in memgrep and the scripts replace LLM repair instructions, shrinking the memory skills
column: design
status: tasked
created: 2026-10-01T17:23:43+0200
updated: 2026-10-01T17:23:43+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T17:23:43+0200
---

# Deterministic auto-fixers in memgrep and the scripts replace LLM repair instructions, shrinking the memory skills

## Owner directive (verbatim, 2026-10-01)

"in general you should automate more repairing using heuristic code in the scripts and in memgrep. linters like ruff are able to auto fix hundreds of issues. take example. this will also help reducing the size of the skills."

## Measured starting point (2026-10-01)

memgrep lint autofixes only publish-globally/symlink drift today (--no-fix to suppress). PROJECT-scope lint finding counts by rule: atom-no-ocd 43, atom-no-lmd 37, atom-oversized 17, lesson-uncited 16, link-one-sided 7. The repair skill sits at 4999/5000 tokens (TRDD-IKZROIE5) because its body spells out mechanical fixes an agent performs by hand.

## Shape (proposal, awaiting owner approval)

ruff model: every lint rule is classified SAFE-FIX (deterministic, provably lossless, applied by memgrep lint --fix) or JUDGMENT (left to the agent). The skills then say: run the fixer, then handle only what it reports as unfixable. Next action: a per-rule classification table with the evidence for each SAFE-FIX verdict, then one rule at a time, each with its own test.

## Approval log

- 2026-10-01T17:23:43+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
