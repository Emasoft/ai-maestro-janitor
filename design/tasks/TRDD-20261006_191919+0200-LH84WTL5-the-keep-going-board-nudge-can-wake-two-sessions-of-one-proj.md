---
trdd-id: LH84WTL5
title: The keep-going board nudge can wake two sessions of one project onto the same card
column: todo
status: tasked
created: 2026-10-06T19:19:19+0200
updated: 2026-10-06T19:19:24+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T19:19:19+0200
---

# The keep-going board nudge can wake two sessions of one project onto the same card

_board_workable_ids (dispatch.py) counts every open dev/todo card regardless of owner, and the nudge text says finishing a card means pulling the next. Two sessions sharing one project (same board, same owner identity, so an owner filter cannot separate them) can both be nudged; since 79255d6e an idle session is woken while the owner works in another pane of the same project, and each card move by the active session changes the board signature and re-arms the idle one. Risk: duplicate work and conflicting writes in one tree. Pre-existing at night (both idle); now reachable in daytime. Fix idea to evaluate, not decided: a per-project nudge lease so only one session at a time receives the zero-agent board nudge, or suppress it while another session of the same project shows recent presence. Also to decide with the owner: whether the nudge should only name cards whose current-owner matches the session agent in ai-maestro projects (RULE 1).

## Approval log

- 2026-10-06T19:19:19+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

NEXT ACTION: measure how often two janitor-armed sessions share one project root on this host (fleet scan), then propose the smallest guard.
