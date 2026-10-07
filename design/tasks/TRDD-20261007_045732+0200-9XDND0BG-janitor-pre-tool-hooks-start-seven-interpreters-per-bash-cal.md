---
trdd-id: 9XDND0BG
title: Janitor pre-tool hooks start seven interpreters per Bash call
column: backburner
status: tasked
created: 2026-10-07T04:57:32+0200
updated: 2026-10-07T04:57:39+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T04:57:32+0200
---

# Janitor pre-tool hooks start seven interpreters per Bash call

Every Bash tool call launches seven janitor PreToolUse hooks, each through the wrapper and its own interpreter start-up; the two all-tool advisory hooks run on every tool call. Under host load this start-up cost is what pushes hooks past their time limit (TRDD-U32EVMI9). Options, none chosen: one process that runs all the checks; or a cheap pre-filter in the wrapper that launches a hook only when the input contains one of its trigger tokens (risk: a too-narrow filter silently skips a check, so it needs tests per hook).

## Acceptance
- [ ] Measured start-up time per Bash call before and after, and every existing hook test still passes.

## Approval log

- 2026-10-07T04:57:32+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

2026-10-07: card created from TRDD-U32EVMI9; no option chosen yet.
