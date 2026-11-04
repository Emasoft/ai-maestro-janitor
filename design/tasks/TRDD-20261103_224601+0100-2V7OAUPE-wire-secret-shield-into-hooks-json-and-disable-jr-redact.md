---
trdd-id: 2V7OAUPE
title: Wire secret-shield into hooks.json and disable jr-redact
column: blocked
status: tasked
created: 2026-11-03T22:46:01+0100
updated: 2026-11-04T01:17:44+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-03T22:46:01+0100
blocked-by: [0Y3UW1NF, TEP6F3A3]
unblock-when: [trdd:0Y3UW1NF terminal, trdd:TEP6F3A3 terminal]
pre-block-column: design
blocker-probe: for i in 0Y3UW1NF TEP6F3A3; do trddgrep --porcelain show $i | cut -f3; done | grep -cE '^(complete|published|live)$'
blocker-holds-if: not-match:^2$
---

# Wire secret-shield into hooks.json and disable jr-redact

## Task
Add "modules": ["./secret-shield/register.ts"] to hooks/hooks.json (path to be confirmed against how hooks.json resolves module paths), disable the jr-redact plugin in the same step, remove "Not active yet." from the three secret_shield_* option descriptions, then run a live probe: a fake token built with printf in Bash output and in an MCP tool result must reach the transcript as a janitor marker, with byte counts of the session .jsonl.
Live probe: for both a normal and an error tool result containing a fake token, the model-facing transcript shows the marker and not the token (TRDD-337UVA3J).

## Blocked by
TRDD-0Y3UW1NF (write-back guard) and TRDD-TEP6F3A3 (checks before wiring). TRDD-337UVA3J does not block it: upstream ships without error-result redaction.

Split out of TRDD-M1218EMH.
- Why the trdd:<id> terminal predicates cannot release this card on a failed, cancelled, superseded or refused blocker: trdd-drift _try_unblock (scripts/detectors/trdd-drift.py) restores a blocked card only when the predicate holds (TERMINAL_COLUMNS) and every blocked-by id is in DONE_COLUMNS, so only complete, published or live releases it, and blocker-probe counts those three. A blocker that ends at completed keeps this card blocked (see TRDD-OEEH2W28). Covered by test_try_unblock_holds_when_blocked_by_is_terminal_but_not_done in tests/test_trdd_drift_unblock_when.py. Still open: if blocked-by is emptied by hand, the predicates alone would release the card.

## Approval log

- 2026-11-03T22:46:01+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-03T22:46:10+0100 — column → blocked. waits for the write-back guard and the pre-wiring checks
