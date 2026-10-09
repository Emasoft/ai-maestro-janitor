---
trdd-id: UASBYABI
title: Should the keep-going board nudge name only cards owned by the receiving session
column: todo
status: tasked
created: 2026-10-09T23:23:38+0200
updated: 2026-10-09T23:23:38+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-09T23:23:38+0200
---

# Should the keep-going board nudge name only cards owned by the receiving session

Carried out of TRDD-LH84WTL5 when it closed on 2026-10-09. That card fixed two sessions of one project being woken onto the same board (a lease, TTL 2700 s). It left one design question open: the nudge lists the whole open board, so a session is told about cards it was never assigned, which sits badly with the rule that a session takes no work without an explicit assignment. Decide from facts: how often the nudge reaches a session whose own cards are all closed, and what the receiving session then does.

## Acceptance

- [ ] The current nudge text and its card selection are read from scripts/dispatch.py and quoted here.
- [ ] A decision is recorded with its basis: keep the whole board, or filter to the session's own cards, or name owned cards first.

## Approval log

- 2026-10-09T23:23:38+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
