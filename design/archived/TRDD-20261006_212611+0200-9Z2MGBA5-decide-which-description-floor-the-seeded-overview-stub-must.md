---
trdd-id: 9Z2MGBA5
title: Decide which description floor the seeded overview stub must meet the lint floor or the authoring floor
column: complete
status: archived
created: 2026-10-06T21:26:11+0200
updated: 2026-10-06T23:46:20+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:26:11+0200
implementation-commits: [e40a8941, 89769546]
---

# Decide which description floor the seeded overview stub must meet the lint floor or the authoring floor

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

Shipped in v3.8.0; GitHub issue #334 closed https://github.com/Emasoft/ai-maestro-janitor/issues/334#issuecomment-6025978684. Landed on main as e40a8941, 89769546.
NEXT ACTION: none; shipped in v3.8.0 and the issue is closed; the owner may still overrule the lint-floor decision.


Source: GitHub issue Emasoft/ai-maestro-janitor#334 (opened 2026-10-06). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The source has two floors, 4 phrases for lint and 15 for authoring. The issue asks which one the seeded stub must meet. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:26:11+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-06T22:08:22+0200 — column → testing by main-agent@ai-maestro-janitor.
- 2026-10-06T23:46:20+0200 — COMPLETE by main-agent@ai-maestro-janitor. shipped in v3.8.0, issue #334 closed.

## Acceptance

- [x] The floor the seeded stub must meet is decided and implemented: the lint floor with an honest description, not the 15-phrase authoring floor. Proof: e40a8941, 89769546; tests/test_session_start_overview_seed_lint.py::test_seeded_overview_stubs_pass_memgrep_lint_with_honest_description; decision stated in the closing comment.
- [x] A closing comment on the issue names the commit and the release. Proof: https://github.com/Emasoft/ai-maestro-janitor/issues/334#issuecomment-6025978684
