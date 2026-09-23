---
trdd-id: FVYV6RSG
title: memgrep lint tickets reach the janitor queue without flooding it
column: todo
created: 2026-09-23T23:05:42+0200
updated: 2026-09-23T23:05:42+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: feature
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-23T23:05:42+0200
---

# memgrep lint tickets reach the janitor queue without flooding it

the owner removed the per-call cap on OPENING tickets (TRDD-XI10BA5D), so dispatch needs its own bound: at most N ticket agents per heartbeat fire; wikimem lint tickets route to the memory curator with the memgrep verb they need, or sit in a visible needs-verb state; ticket bodies carry page id, rule code and anchor, never page text; one ticket per USER-scope issue across projects; the owner hold on the AgentlensPro and ghbook pages is respected.

## Approval log

- 2026-09-23T23:05:42+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
