---
trdd-id: 350W5II2
title: Jev scores only live tool and event items, not pre-boundary ones
column: todo
created: 2026-09-24T14:12:56+0200
updated: 2026-09-24T18:14:56+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: refactor
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: user
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-24T14:12:56+0200
pre-block-column: 
blocked-by: []
blocker-probe: [trddgrep, --porcelain, show, D7RLXAN1]
blocker-holds-if: not-match:\t(complete|completed|cancelled|superseded)\t
status: tasked
---

# Jev scores only live tool and event items, not pre-boundary ones

Follow-up to TRDD-D7RLXAN1 (Jev keeps every owner/assistant message verbatim and never scores it), out of that card's scope.

Advisor review (reports/compaction-replacement/20260924_140604+0200-advisor-prose-verbatim.md, §7, first bullet): split_conversation scores ALL tool/event items, pre-boundary included. The digest is built from the newest prose, so pre-boundary tool results are scored against a task they predate; on 4eb7bf5d (78 boundaries, 258 MB) that is thousands of items and most of the Jev time (score_items docstring, scripts/lib/jev_compaction.py:948-951: 168 s serial on 7,075 items).

Change: restrict scored to LIVE items only, using the same is_live predicate D7RLXAN1 defines for conversation items (turn >= boundary_turn or uuid in preserved_uuids) applied to tool/event items too. This applies D7RLXAN1's own logic ("what the cleared context actually contained") to tool items, cuts Jev cost and time, and makes the injected non-owner floor draw from live items only. expand <id> still reaches pre-boundary items by uuid (scripts/jev_compact.py:358-380) — nothing becomes unreachable, only unscored.

Sequencing: depends on D7RLXAN1 landing first (needs its window/is_live machinery). Likely the largest remaining Jev cost lever (inferred from the score_items docstring, not measured), named by the advisor but explicitly out of D7RLXAN1's scope.

Related: TRDD-D7RLXAN1 (builds on its window/boundary machinery; the advisor named this as the next follow-up).

## Approval log

- 2026-09-24T14:12:56+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-24T14:24:55+0200 — column → blocked by emanuelesabetta. reuses D7RLXAN1's window/is_live machinery; cannot start until D7RLXAN1 lands
- 2026-09-24T18:14:56+0200 — column → todo by emanuelesabetta. D7RLXAN1 landed (implementation-commits: c7779d84); its window/is_live machinery is now available to build on Cleared blocked-by (--clear-blocker override).

## Timing evidence

The real post-clear hook (run_hook.py) took 46 s on accccb8b against the hook's 60 s run_compact bound, at load average 50-117 -- 18 s on the same session this morning (D7RLXAN1 acceptance (e)), so load variance alone can trip a re-run into the template fallback. One more spike over 60 s loses Jev entirely for that session. Scoring only live items (this card) is the root fix -- D7RLXAN1's split_conversation still scores ALL tool/event items including pre-boundary ones (score_items docstring: 168 s serial on 7,075 items on 4eb7bf5d), which is most of that 46 s.
