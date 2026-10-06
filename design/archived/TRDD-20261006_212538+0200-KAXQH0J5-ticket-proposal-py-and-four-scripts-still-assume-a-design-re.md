---
trdd-id: KAXQH0J5
title: ticket_proposal.py and four scripts still assume a design/refused folder the owner abolished
column: complete
status: archived
created: 2026-10-06T21:25:38+0200
updated: 2026-10-06T23:45:24+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:38+0200
implementation-commits: [237cf471]
---

# ticket_proposal.py and four scripts still assume a design/refused folder the owner abolished

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

Shipped in v3.8.0; GitHub issue #309 closed https://github.com/Emasoft/ai-maestro-janitor/issues/309#issuecomment-6025971155. Landed on main as 237cf471 (code fix ad72b57e in v3.7.1).
NEXT ACTION: none; shipped in v3.8.0 and the issue is closed.


Source: GitHub issue Emasoft/ai-maestro-janitor#309 (opened 2026-09-24). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The owner ruled that a refused card stays in proposals as a column, is never archived by the manager, and that no design/refused zone exists. ticket_proposal.py and four other scripts still assume that zone. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:38+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-06T22:08:22+0200 — column → testing by main-agent@ai-maestro-janitor.
- 2026-10-06T23:45:24+0200 — COMPLETE by main-agent@ai-maestro-janitor. shipped in v3.8.0, issue #309 closed.

## Acceptance

- [x] The scripts no longer assume a design/refused folder; refused is a column, never a folder. Proof: ad72b57e (v3.7.1); tests/test_trdd_common.py::test_design_folders_match_the_owner_ruling_no_refused_zone and tests/test_refusal_aware_proposals.py.
- [x] The shipped rule text is aligned with the owner ruling. Proof: 237cf471 (v3.8.0).
- [x] A closing comment on the issue names the commit and the release. Proof: https://github.com/Emasoft/ai-maestro-janitor/issues/309#issuecomment-6025971155
