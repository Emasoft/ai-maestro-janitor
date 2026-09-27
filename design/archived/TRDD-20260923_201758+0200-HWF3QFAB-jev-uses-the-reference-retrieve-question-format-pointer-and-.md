---
trdd-id: HWF3QFAB
title: Jev uses the reference RETRIEVE_QUESTION, format_pointer and asks the decision question only of the user's own messages
column: complete
created: 2026-09-23T20:17:58+0200
updated: 2026-09-27T13:07:01+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: refactor
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-23T20:17:58+0200
derived: true
parent-trdd: RAEGS1D5
status: archived
---

# Jev uses the reference RETRIEVE_QUESTION, format_pointer and asks the decision question only of the user's own messages

Card 5 of the Jev reference gap analysis (2026-09-23, owner: most reference functions are not implemented). Now that jevctx/pipeline.py is vendored verbatim (commit 49d733b7), jev_compaction.py must stop using its drifted copies: RELEVANCE_QUESTION becomes pipeline.RETRIEVE_QUESTION (ours mixed an ADMIT-style clause into it and invented the true/false text); _ref_question is imported from jevctx.scorer (byte-identical duplicate today); _format_pointer uses pipeline.format_pointer (escaping, lines=, summary = first NON-EMPTY line). Plan user items at 16 per batch (2 questions) and the rest at 32 (1 question), which roughly halves the batch count and the digest re-billing. Update VENDORED.md to say the pipeline symbols are now used. Tests: FakeJevClient calls show no decision question for non-user refs; every pointer in a compose() output parses with find_pointers and the count equals the elided items shown; no batch exceeds 32 questions. Acceptance: on one real transcript the request count drops and decision_passed is never true for a non-user item. Depends on card 1 (TRDD-RAEGS1D5 classifier) and card 4 (49d733b7). Blocks the Jev publish: without it the vendored pipeline.py is unused code.

## Approval log

- 2026-09-23T20:17:58+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-23T21:10:50+0200 — column → testing. code landed and committed 2026-09-23 with tests; awaiting the real-transcript compaction on the final tree and the release
- 2026-09-27T13:07:01+0200 — COMPLETE by user. owner batch acceptance 2026-09-27 ('complete all TRDDs'); independent lean-worker verdict DONE (batch2), evidence named per box.

## Acceptance

- [x] scripts/lib/jev_compaction.py:38 imports RETRIEVE_QUESTION/format_pointer from jevctx.pipeline; VENDORED.md documents the vendor rule; code+tests+real-transcript acceptance recorded
- [x] worker re-ran the card's named tests on HEAD 2026-09-27 (batch2 report carries commands + results); owner batch acceptance 2026-09-27 ("complete all TRDDs")
