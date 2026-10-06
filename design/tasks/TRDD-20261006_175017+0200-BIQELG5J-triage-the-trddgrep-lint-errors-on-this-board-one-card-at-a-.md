---
trdd-id: BIQELG5J
title: Triage the trddgrep lint errors on this board one card at a time
column: todo
status: tasked
created: 2026-10-06T17:50:17+0200
updated: 2026-10-06T17:51:50+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T17:50:17+0200
---

# Triage the trddgrep lint errors on this board one card at a time

Requested by the ai-maestro hub session (2026-10-06 self-review). trddgrep lint exits 1 with errors including MANDATE-FORGED x1, ZONE-MISMATCH x13, GRAPH-FALSE-COMPLETE x4, TERMINAL-WITH-OPEN-BOX x17, TERMINAL-WITHOUT-CHECKLIST x69, LEGACY-REFUSED-FOLDER (3 cards in design/refused/). Per-card judgment, never a mass script; cards entered on or before 2026-08-23 are grandfathered under 3P-KAN-21. Start with MANDATE-FORGED and ZONE-MISMATCH. NEXT ACTION: run trddgrep lint --rule MANDATE-FORGED and read that card.

## Approval log

- 2026-10-06T17:50:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

2026-10-06 NEXT ACTION: run trddgrep lint --rule MANDATE-FORGED and read that card.
