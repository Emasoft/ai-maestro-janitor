---
trdd-id: DCI0BG66
title: prrdgrep show fails for a bare rule number such as 33 although 33.1 and G33.1 work
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

# prrdgrep show fails for a bare rule number such as 33 although 33.1 and G33.1 work

## Symptom (by the orchestrator, 2026-11-19, unverified unless stated)

- prrdgrep show 33 fails with: no PRRD record "33". show 33.1 and show G33.1 work.
- The PRRD design rule says tools must accept the number alone and ignore any G/S letter.
- The tool is not janitor code: ~/.local/bin/prrdgrep is a launcher that dispatches to the ai-maestro install (hypothesis, not verified: the implementation is under lib/pillar/ of the ai-maestro project, https://github.com/Emasoft/ai-maestro; upstream of the fork is 23blocks-OS/ai-maestro). Nothing is posted anywhere; the owner decides whether to file an issue there (the rule git-and-destructive-safety applies).

## Governing

PRRD G34.1.

## Done means

- [ ] Reproduced or shown absent, then filed with the ai-maestro project (owner decision) and a janitor-side note until fixed.

## Approval log

- 2026-11-19T12:34:09+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
