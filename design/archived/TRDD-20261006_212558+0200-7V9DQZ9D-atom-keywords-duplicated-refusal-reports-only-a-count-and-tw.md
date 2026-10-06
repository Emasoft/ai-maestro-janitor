---
trdd-id: 7V9DQZ9D
title: atom-keywords-duplicated refusal reports only a count and two phrase conventions coexist
column: complete
status: archived
created: 2026-10-06T21:25:58+0200
updated: 2026-10-07T00:03:54+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:58+0200
implementation-commits: [cf64735b]
---

# atom-keywords-duplicated refusal reports only a count and two phrase conventions coexist

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

Shipped in v3.8.0; GitHub issue #323 closed https://github.com/Emasoft/ai-maestro-janitor/issues/323#issuecomment-6025975300. Landed on main as cf64735b.
NEXT ACTION: none, no code release needed; the declined item is recorded as a decision (owner may veto).


Source: GitHub issue Emasoft/ai-maestro-janitor#323 (opened 2026-09-29). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The refusal names only the number of duplicate keywords, not which ones, and two conventions for delimiting phrases coexist, so a grammar mistake becomes an unexplained wall. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:58+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-06T22:08:21+0200 — column → testing by main-agent@ai-maestro-janitor.
- 2026-10-07T00:03:54+0200 — COMPLETE by main-agent@ai-maestro-janitor. declined item recorded as a decision; fix cf64735b shipped in v3.8.0; self-approved by this standalone session.





## Acceptance

- [x] The duplicate-keyword refusal states the two keyword-delimiting conventions. Proof: cf64735b; scripts/memgrep/src/memory.rs::keywords_duplicated_message_states_the_two_conventions_without_echoing_keywords.
- [x] The refusal names WHICH keywords are duplicated, not only the count. Declined by design, owner may veto - see #323 closing comment: refusals never quote page content.
- [x] A closing comment on the issue names the commit and the release. Proof: https://github.com/Emasoft/ai-maestro-janitor/issues/323#issuecomment-6025975300
