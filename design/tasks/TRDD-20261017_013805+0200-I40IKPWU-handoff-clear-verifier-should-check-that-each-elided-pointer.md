---
trdd-id: I40IKPWU
title: Handoff-clear verifier should check that each elided pointer expands
column: dev
status: tasked
created: 2026-10-17T01:38:05+0200
updated: 2026-10-17T03:38:45+0200
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
implementation-commits: [23e1b3e0]
---

# Handoff-clear verifier should check that each elided pointer expands

Split from TRDD-AFW0CA65 (7b67bab6). After 7b67bab6, handoff_links_resolve skips Jev pointers ([[elided id=...]]) because they are expand handles, not wikilinks; on today's link-only handoffs that check reports SKIP. The only real recoverability test for elided content is that each pointer in the handoff resolves with `jev_compact.py expand --transcript <t> <id>`. To do: add a verifier check (before/after phase) that expands every pointer id against the cleared transcript and FAILs on any that does not resolve; measure on the existing handoffs first.

## Approval log

- 2026-10-17T01:38:05+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-17

- Column dev. Step 1 DONE: 23e1b3e0 pins the full stderr line of six expand error paths.
- Step 2 BUILDING (worker): spec docs_dev/20261017_022708+0200-I40IKPWU-build-spec.md + amendments docs_dev/20261017_023510+0200-I40IKPWU-spec-amendments.md + nine review corrections E1-E9 (real-pointer positions only: inline after its own message header with matching id, or after the last exact `## Elided`; unrecognised pointer format = FAIL; transcript only from the block last `pointers expand with:` line; projects root = CLAUDE_CONFIG_DIR/projects or ~/.claude/projects, resolved; check and open the same resolved path; validate_transcript_path(path|None, roots, sid8); _tool_result_text renamed public tool_result_text in jev_expand; smoke run uses pure functions only; malformed-line + failure stderr order pinned).
- Design: new stdlib-only scripts/lib/jev_expand.py (read_jsonl_entry, extract_block, tool_result_text, attachment_item_text, resolve_pointer) because the verifier is a dependency-free script and jevctx needs httpx; verifier verdict handoff_pointers_expand.
- Reviews/measurements: round 1 + round 2 adversarial reviews, two spec reviews, MEASURE reports docs_dev/20261017_021819+0200-I40IKPWU-measure.md and docs_dev/20261017_022455+0200-I40IKPWU-measure2.md.
- Framing: regression guard for an invariant that holds today (405/405 pointers resolved); no failure observed. The earlier c436b9d9 "vanished transcript" claim was REFUTED (file exists).
- Coverage limits: the check runs only on clear paths that call handoff_clear_verify.py; a "transcript missing" FAIL is meaningful only right after a clear (later it is normal ageing); "transcript path rejected" is a separate FAIL class judging handoff well-formedness.
- Lifecycle note: moved todo -> dev directly; verify_assumptions/plan/dispatch were done in substance (the measurements, reviews and spec above).
- NEXT ACTION: when step 2 reports, verify its report and diff, run the four checks, commit the feature with TRDD-I40IKPWU in the subject, add that SHA here, move to testing.
