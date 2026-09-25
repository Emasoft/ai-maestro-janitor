---
trdd-id: SK490HKU
title: Jev injected copy leaves its room unused while live over-cap tool results are pointer-only
column: backburner
status: tasked
created: 2026-09-25T00:05:16+0200
updated: 2026-09-25T06:23:13+0200
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
2026-09-25 (second fill pass, TRDD-SK490HKU implementation): inline non-owner (tool/event) blocks in the injected copy, before (HEAD 90e890ce) -> after -- b2bf5b7b 7->7 (room already fully spent by primary tiers, no over-cap item fit), d30bf250 0->3 (bytes 4006->6004), 4eb7bf5d 1->1 (unchanged: Jev kept only one live item, already inline), fd5cc3e0 0->2 (bytes 2992->5430). Measured against today's real room sizing (6012-6036 B via jcl.trim_cards_for_room, not the ~3,900 B the advisor's report measured at 05:44 -- room grows with the live board), via scripts_dev/sk49/measure_second_pass.py. All 141 tests in tests/test_jev_compaction.py pass (4 new: two exactness/highest-score-first tests plus the two report-named tests split into small-room/large-room pairs); ruff/mypy/pyright clean. --out byte-identity unaffected (confirmed by the existing test).
2026-09-25 review follow-up: adversarial review of the implementation found no correctness defect by tracing, but flagged two coverage gaps -- (1) no test exercised the second pass's interaction with the owner-overflow/decision-pointer tiers under room pressure (the exact shape of a bug already caught once during implementation, a missing 'not in inline_ids' filter), and (2) the rewritten decision-pointer test no longer proved max_elided_pointers caps ORDINARY tool/event pointers in the injected copy once Jev-kept over-cap items exist. Both closed: test_injected_second_pass_leaves_max_elided_pointers_capping_the_rest (6 over-cap tool items, room for exactly 4 whole, the other 2 still capped/pointed at max_elided_pointers=2) and test_injected_second_pass_does_not_disturb_the_decision_pointer_reserve (an excluded decision-passing owner pointer survives unchanged alongside a competing over-cap tool item). Both verified to fail on HEAD (scripts_dev/sk49/verify_fail_on_head.py, now 6 checks, all fail on HEAD). Full suite still 299 passed; ruff/mypy/pyright clean.
