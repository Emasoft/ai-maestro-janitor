---
trdd-id: 1HXEAHY7
title: C32 — shrink enrich skill
column: testing
status: tasked
created: 2026-10-01T19:45:19+0200
updated: 2026-10-09T17:22:19+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:19+0200
blocked-by: []
pre-block-column: todo
blocker-probe: [trddgrep, why, 1HXEAHY7]
blocker-holds-if: not-match:READY
---

# C32 — shrink enrich skill

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C32, wave W3.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-09

NEXT ACTION: the Pass-1 field run — run the NEW enrich skill's Pass 1 (memgrep lint --apply-fixes on the claimed candidate paths, then Pass 2 additive fixes, then the plain re-lint verifier) on a real scope root; this run is ALSO the evidence event C22's (JD2QR5SQ) completion gate awaits. A zero-refusal outcome is the already-ruled clean-corpus case (JD2QR5SQ escalation clause), not a failure. Implementation is COMMITTED (c18ee75d); the skill's lint --apply-fixes surface verified on PATH 2026-10-09. Move the column per the field run's outcome (success → testing/ai_review; only dev while the run is imminent). Owner may correct.

Writes (exclusive): skills/janitor-memory-enrich/SKILL.md
Task: Same as C31, for the dedupe items
Verify: Same as C31
Depends on: C22 — SATISFIED-THEN-COUPLED, not blocking (disposition in the Approval log, 2026-10-09; the coupling is that this card's Pass-1 run is the evidence-event shape C22's gate awaits — tracked by the escalation clause on JD2QR5SQ, read the count there)
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:19+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:22+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on JD2QR5SQ per DSN035UN wave order
- 2026-10-08 (probe caveat, corpus sweep): this why-probe's holds-if is not-match:READY against trddgrep why output — two known ceilings: (1) a future blocker card whose TITLE contains the word READY false-unblocks this card (grep is not column-aware here); (2) the zero-open-prereq->READY transition was never observed on a flipping card (endpoints only) — trddgrep may never print READY after an archived blocker (known tooling gap). Treat a probe release as a PROMPT TO RE-VERIFY the chain, not proof of unblocked.
- 2026-10-09T05:31:52+0200 — column → todo. Same deadlock resolution as C30 (I4MOD020): the C22 dependency is a completion-event coupling — C32's Pass-1 run is C22's awaited evidence, so blocking C32 on C22 deadlocks the circle. Freeze treated as lifted (agent inference, owner may correct). C32 unblocked.
2026-10-09 dependency disposition (per the review on 6e450b80): the body 'Depends on: C22' is SATISFIED-THEN-COUPLED, not blocking — C22's code exists and C32's Pass-1 run is the evidence EVENT SHAPE C22's gate awaits, with the same evidence expectation as C30: on the present clean corpus a run has nothing to refuse; a zero-refusal outcome is the already-ruled clean-corpus case tracked by JD2QR5SQ's escalation clause — read the count there; not a pending mystery. The work itself (shrink the enrich skill, same methodology as C31 with the cap re-measure) is unblocked and developable.
- 2026-10-09T05:53:46+0200 — column → dev. unblocked per 2026-10-09 SATISFIED-THEN-COUPLED disposition; fan-out worker starts
2026-10-09T11:45:00+0200 — Pass-1 FIELD RUN executed (coordinator, on the real PROJECT memory root .claude/project/memory): pre-lint 111 findings none-ERROR with ZERO fixer-owned hits (atom-keywords-duplicated: 0, page-description-duplicated-phrases: 0); memgrep lint --apply-fixes exit 0, no pages modified, zero refusals; post-lint verifier 111 findings, sorted diff vs pre-lint = 0; git tree clean. This is the ruled CLEAN-CORPUS outcome (JD2QR5SQ escalation clause) — the run also satisfies C22's awaited evidence event. Implementation committed c18ee75d; lint --apply-fixes surface verified on PATH. Card verify-clause (Same as C31) met on the real root.
