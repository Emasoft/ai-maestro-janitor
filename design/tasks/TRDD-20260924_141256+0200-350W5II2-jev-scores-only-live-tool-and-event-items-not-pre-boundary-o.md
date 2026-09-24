---
trdd-id: 350W5II2
title: Jev scores only live tool and event items, not pre-boundary ones
column: todo
created: 2026-09-24T14:12:56+0200
updated: 2026-09-25T00:06:08+0200
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

## Implementation

split_conversation (scripts/lib/jev_compaction.py) now returns (conversation, scored, pre_boundary): scored = LIVE tool/event items only (window.is_live applied, same predicate D7RLXAN1 uses for prose); pre_boundary counts what was dropped, surfaced as pre_boundary=N in cmd_compact's summary line (jev_compact.py), appended after malformed=N. jev_compaction_lane.py's blocked=/malformed= regexes are substring searches, unaffected by the trailing field (pinned by test). expand <id> unaffected -- resolves any item by uuid regardless of liveness.

## Acceptance

Wall time and cost, real OpenRouter calls, same transcript. Before = exact HEAD 8a5f3852 scripts/jev_compact.py + scripts/lib/jev_compaction.py (byte-identical to git show) swapped into the tree; after = this change. 4eb7bf5d (258 MB, 22754 items, boundary_turn=22603): before ms=30417 items=5305/14972 cost=$0.249; after ms=5455 items=47/125 cost=$0.00185; pre_boundary=14847 (99.2% of the old scored set). accccb8b (7.5 MB, no compact_boundary): pre_boundary=0, so the scored set is identical by construction; after ms=2038. Injected copy (re-render of the 4 cached sessions with cached Jev scores, no new Jev call; before = scripts_dev/350w-scratch/rerender_head.py on HEAD jev_compaction.py, after = scripts_dev/d7-scratch/rerender_d7.py, run back to back, the after run repeated with identical output): inline tool/event blocks before -> after: 4eb7bf5d 8->1, b2bf5b7b 7->7 (no boundary, identical), d30bf250 8->0, fd5cc3e0 10->0. unexplained_count=0 and summary_ok=true on every run, so no live prose is lost. Cause of the drop, traced through _select_injected: every inline block HEAD showed was a pre-boundary item (agent notifications, small tool segments). The new code inlines every inline-eligible live candidate (4eb7bf5d 1 of 1, d30bf250 0 of 0, fd5cc3e0 0 of 0) with room to spare (2.4-3.4 KB unused), but the live items Jev kept are almost all tool results over the per-item cap, which compose already makes pointer-only (TRDD-BLGZTHQ9). So the injected copy's tool/event section is empty on 2 of 3 boundary sessions and its room goes unused: the spec condition that live-only scoring must not starve the injected copy is NOT met as measured. Decision pending: accept (pre-boundary content is covered by the compaction summary and by expand) or follow up on the over-cap tool rule and the unused room. An earlier version of this paragraph compared against scripts_dev/d7-scratch/old-lib, which differs from HEAD by about 200 diff lines, and misattributed the b2bf5b7b and fd5cc3e0 numbers; this paragraph supersedes it.

## Decision

2026-09-25 (main session, under the owner's delegated authority, verbatim 2026-09-24: "i've given full authority to decide by yourself, just made the decisions on the base of verified facts and tests. thats it. but go on and deliver the plugin that implements the jev-compaction! we are late!"): ACCEPT the injected-copy drop and commit. Every inline block HEAD showed was a pre-boundary item, which the compaction summary covers and `expand <id>` still reaches; no live prose is lost (unexplained_count=0, summary_ok=true on every run); and the change drops 99.2% of the scored set on 4eb7bf5d (30.4 s to 5.5 s, $0.249 to $0.00185), the root fix for the 46 s against 60 s post-clear hook bound. Verified 2026-09-25 before commit: 313 Jev tests pass, ruff, mypy and pyright clean, every split_conversation caller unpacks 3 values (docs_dev/20260925_000512+0200-trdd-350w5ii2-verify.md). The unmet condition (live over-cap tool results pointer-only while the injected room goes unused) moves to TRDD-SK490HKU.
