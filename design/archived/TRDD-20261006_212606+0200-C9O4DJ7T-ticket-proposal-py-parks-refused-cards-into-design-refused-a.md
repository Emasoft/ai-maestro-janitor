---
trdd-id: C9O4DJ7T
title: ticket_proposal.py parks refused cards into design/refused and git-deletes the proposals original
column: complete
status: archived
created: 2026-10-06T21:26:06+0200
updated: 2026-10-06T23:47:22+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:26:06+0200
implementation-commits: [ad72b57e, 237cf471]
---

# ticket_proposal.py parks refused cards into design/refused and git-deletes the proposals original

Source: GitHub issue Emasoft/ai-maestro-janitor#329 (opened 2026-10-03). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The withdrawal machinery recreated the abolished design/refused zone in another repo and git-deleted the committed original under design/proposals. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:26:06+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-06T23:47:22+0200 — COMPLETE by main-agent@ai-maestro-janitor. shipped in v3.8.0, issue #329 closed.

## Acceptance

- [x] The withdrawal machinery no longer creates design/refused nor git-deletes the committed original under design/proposals. Proof: ad72b57e (v3.7.1); tests/test_issue_catalog.py::test_retract_never_creates_a_refused_folder_nor_removes_the_original and test_retract_leaves_a_human_refused_card_byte_identical.
- [x] A closing comment on the issue names the commit and the release. Proof: https://github.com/Emasoft/ai-maestro-janitor/issues/329#issuecomment-6025971927

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

Shipped in v3.8.0 (code fix ad72b57e in v3.7.1, rule text 237cf471 in v3.8.0); GitHub issue #329 closed https://github.com/Emasoft/ai-maestro-janitor/issues/329#issuecomment-6025971927.
NEXT ACTION: none; shipped and the issue is closed. (This card had no STATE block; created at the end of the card because trddgrep append cannot place it under the title.)
