---
trdd-id: R9UXOSR5
title: Retire the decision question and owner tiers once prose is never scored
column: backburner
created: 2026-09-24T14:12:48+0200
updated: 2026-09-24T14:12:48+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: refactor
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: user
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-24T14:12:48+0200
---

# Retire the decision question and owner tiers once prose is never scored

Follow-up to TRDD-D7RLXAN1 (Jev keeps every owner/assistant message verbatim and never scores it). Sequenced AFTER D7RLXAN1's acceptance run passes.

Advisor review (reports/compaction-replacement/20260924_140604+0200-advisor-prose-verbatim.md, §6, VERIFIED): once no kind=="user" item reaches score_items, compose or log_decisions, every listed symbol is a no-op.

Remove (verify each with tldr impact first): DECISION_QUESTION and the asks_decision path; the user group in score_items; the decision-threshold CLI/env (scripts/jev_compact.py:175 _DECISION_ENV, :608/:645 threshold passthrough, :779 --decision-threshold flag) — there is NO matching userConfig option in .claude-plugin/plugin.json (grep for a jev_ option finds none), so nothing user-visible is removed; jev_shadow_log's decision dimension (scripts/lib/jev_shadow_log.py:576-587 retrieve row, :27/:227 replay --question relevance|decision, _RETRIEVE_ROW_ID_SUFFIX :242) — retiring the decision question retires replay --question decision too, old on-disk retrieve rows become unselectable; the owner and decision tiers of _select_injected (steps 1, 3, 4 and 6) and their constants; Scores.decision_passed and evict_key's decision_passed term (becomes constant-False, goes with the rest).

Must stay (about tool/event items, not the decision question): Item.protected/_effective_protected (:1881-1893), _NON_OWNER_FLOOR, _INJECT_MIN_BODY_CHARS, _notification_block, _tool_result_part; is_control_input (external_clear.py:598,609 and extract_items).

Scale: tests/test_jev_compaction.py has 138 decision_passed references, tests/test_jev_shadow_log.py 7, tests/test_jev_compact_cli.py 2 — a large rewrite, not a same-commit cleanup; make it its own commit so a review of D7RLXAN1's behaviour change is not buried under test churn.

TRDD-98SP58TJ is then superseded (confirm it is only about the decision question first).

Related: TRDD-D7RLXAN1 (this card is D7RLXAN1's dead-code follow-up, split out per advisor §6/§7 recommendation).

## Approval log

- 2026-09-24T14:12:48+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
