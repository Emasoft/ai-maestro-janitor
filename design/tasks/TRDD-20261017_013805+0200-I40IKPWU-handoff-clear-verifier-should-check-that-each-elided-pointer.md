---
trdd-id: I40IKPWU
title: Handoff-clear verifier should check that each elided pointer expands
column: testing
status: tasked
created: 2026-10-17T01:38:05+0200
updated: 2026-10-17T04:41:43+0200
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
approval-datetime: 2026-10-17T01:38:05+0200
implementation-commits: [23e1b3e0, 939a1f19]
---

# Handoff-clear verifier should check that each elided pointer expands

Split from TRDD-AFW0CA65 (7b67bab6). After 7b67bab6, handoff_links_resolve skips Jev pointers ([[elided id=...]]) because they are expand handles, not wikilinks; on today's link-only handoffs that check reports SKIP. The only real recoverability test for elided content is that each pointer in the handoff resolves with `jev_compact.py expand --transcript <t> <id>`. To do: add a verifier check (before/after phase) that expands every pointer id against the cleared transcript and FAILs on any that does not resolve; measure on the existing handoffs first.

## Approval log

- 2026-10-17T01:38:05+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-17

- Column dev. Step 1 DONE: 23e1b3e0 pins the full stderr line of six expand error paths.
- Step 2 DONE: 939a1f19. Contents: jev_expand.py (stdlib-only); the handoff_pointers_expand verdict; pointers counted only in the Newest-messages section (headings '## Newest messages' or '## Conversation since') and after the last '## Elided'; the format-drift count limited to the same regions. Full suite 18539 passed before the review fixes; 253 targeted tests passed after; ruff, mypy and pyright clean.
- Design: new stdlib-only scripts/lib/jev_expand.py (read_jsonl_entry, extract_block, tool_result_text, attachment_item_text, resolve_pointer) because the verifier is a dependency-free script and jevctx needs httpx; verifier verdict handoff_pointers_expand.
- Reviews/measurements: round 1 + round 2 adversarial reviews, two spec reviews, MEASURE reports docs_dev/20261017_021819+0200-I40IKPWU-measure.md and docs_dev/20261017_022455+0200-I40IKPWU-measure2.md.
- Framing: regression guard for an invariant that holds today (405/405 pointers resolved); no failure observed. The earlier c436b9d9 "vanished transcript" claim was REFUTED (file exists).
- Coverage limits: the check runs only on clear paths that call handoff_clear_verify.py; a "transcript missing" FAIL is meaningful only right after a clear (later it is normal ageing); "transcript path rejected" is a separate FAIL class judging handoff well-formedness.
- Lifecycle note: moved todo -> dev directly; verify_assumptions/plan/dispatch were done in substance (the measurements, reviews and spec above).
- NEXT ACTION: field proof after a release ships it. On a real /clear, the verifier report shows the row 'every elided pointer in the handoff expands' as PASS. Follow-up (not this card): extract_block's tool_result list branch could call tool_result_text.
- Verified after the review fixes (2026-10-17): full suite on 939a1f19 = 18542 passed, 2 skipped, exit 0. The pure check over all 183 real handoffs = 95 PASS, 88 SKIP (no pointers), 0 FAIL, including the 86 handoffs carrying '## Conversation since' (that section holds only user/assistant exchange blocks, jev_compaction.py:2120-2125). Residual: a user or assistant message that itself quotes a header plus a matching pointer would be checked against the wrong transcript; rare, and it would be a loud FAIL, not a silent pass.
Follow-up (not this card): in scripts/lib/jev_expand.py, extract_block's tool_result list branch could call tool_result_text. Keep the string branch, and keep None (not empty string) for other shapes. Cosmetic leftovers: three blank lines in two places, in scripts/handoff_clear_verify.py and tests/test_jev_compact_cli.py.
