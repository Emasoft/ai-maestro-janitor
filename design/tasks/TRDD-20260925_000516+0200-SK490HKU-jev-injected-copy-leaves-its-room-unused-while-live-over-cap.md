---
trdd-id: SK490HKU
title: Jev injected copy leaves its room unused while live over-cap tool results are pointer-only
column: backburner
status: tasked
created: 2026-09-25T00:05:16+0200
updated: 2026-09-25T03:34:27+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-09-25T00:05:16+0200
---

# Jev injected copy leaves its room unused while live over-cap tool results are pointer-only

Follow-up to TRDD-350W5II2, which moved scoring to LIVE tool/event items only. Measured on 2026-09-24 (TRDD-350W5II2 Acceptance): inline tool/event blocks in the injected copy went 8->1 (4eb7bf5d), 8->0 (d30bf250), 10->0 (fd5cc3e0), 7->7 (b2bf5b7b, no boundary). Every block HEAD showed was a pre-boundary item. The live items Jev keeps are almost all tool results over the per-item cap, which compose makes pointer-only (TRDD-BLGZTHQ9), so the injected copy's tool/event section is empty on 2 of 3 boundary sessions while 2.4-3.4 KB of its room goes unused. Goal: use that room for the highest-scored live tool results (for example a trimmed head of an over-cap result, or relaxing the cap when room remains), without re-admitting pre-boundary items and without breaking the injected budget. Acceptance: on the same 4 sessions, the injected copy shows at least one live tool/event block wherever Jev kept any live tool item, the injected budget holds, and no live prose is lost (unexplained_count=0, summary_ok=true).

## Approval log

- 2026-09-25T00:05:16+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Measurements

2026-09-25 on 90e890ce: the injected copy is 3,902 / 2,547 / 3,557 / 2,649 B on b2bf5b7b / d30bf250 / 4eb7bf5d / fd5cc3e0, far under its 8,192 B limit. 90e890ce (TRDD-BLGZTHQ9) also makes over-cap non-notification event items (peer messages) pointer-only, which frees more room that the selection does not reuse; whether peer messages should instead show a labelled excerpt is an open owner decision.
