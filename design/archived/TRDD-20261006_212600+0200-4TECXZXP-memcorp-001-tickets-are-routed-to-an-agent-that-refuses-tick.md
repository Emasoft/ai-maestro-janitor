---
trdd-id: 4TECXZXP
title: MEMCORP-001 tickets are routed to an agent that refuses ticket work and dispatched without re-validation
column: complete
status: archived
created: 2026-10-06T21:26:00+0200
updated: 2026-10-06T23:46:15+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:26:00+0200
implementation-commits: [27974a16]
---

# MEMCORP-001 tickets are routed to an agent that refuses ticket work and dispatched without re-validation

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

Shipped in v3.8.0; GitHub issue #324 closed https://github.com/Emasoft/ai-maestro-janitor/issues/324#issuecomment-6025975911. Landed on main as 27974a16.
NEXT ACTION: none; shipped in v3.8.0 and the issue is closed.


Source: GitHub issue Emasoft/ai-maestro-janitor#324 (opened 2026-09-30). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: Memory corpus tickets are routed to the memory subconscious agent, which refuses them, and the repair agent they are re-dispatched to also refuses. They are also titled with the wrong scope and dispatched without re-validation. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:26:00+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-06T22:08:21+0200 — column → testing by main-agent@ai-maestro-janitor.
- 2026-10-06T23:46:15+0200 — COMPLETE by main-agent@ai-maestro-janitor. shipped in v3.8.0, issue #324 closed.





## Acceptance

- [x] Memory-corpus tickets are never dispatched to an agent that refuses them. Proof: 27974a16; tests/test_memcorp_ticket_handoff.py::test_a_memory_corpus_ticket_is_never_handed_to_the_ticket_marker and test_select_due_skips_kinds_flagged_not_dispatchable.
- [x] An open ticket is re-validated: one whose finding is gone is closed invalid, one that still reproduces stays open. Proof: 27974a16; tests/test_memcorp_ticket_handoff.py::test_an_open_ticket_whose_finding_is_gone_is_closed_invalid and test_an_open_ticket_whose_finding_still_reproduces_stays_open.
- [x] The wrong-scope title symptom needs no change. Proof: 27974a16 commit message (the title scope label was already the single-source label, LOCAL); tests/test_memcorp_ticket_handoff.py builds the ticket with scope LOCAL.
- [x] A closing comment on the issue names the commit and the release. Proof: https://github.com/Emasoft/ai-maestro-janitor/issues/324#issuecomment-6025975911
