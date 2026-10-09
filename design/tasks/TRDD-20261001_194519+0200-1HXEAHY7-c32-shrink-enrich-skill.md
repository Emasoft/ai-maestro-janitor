---
trdd-id: 1HXEAHY7
title: C32 — shrink enrich skill
column: todo
status: tasked
created: 2026-10-01T19:45:19+0200
updated: 2026-10-09T05:35:06+0200
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

Writes (exclusive): skills/janitor-memory-enrich/SKILL.md
Task: Same as C31, for the dedupe items
Verify: Same as C31
Depends on: C22
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:19+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:22+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on JD2QR5SQ per DSN035UN wave order
- 2026-10-08 (probe caveat, corpus sweep): this why-probe's holds-if is not-match:READY against trddgrep why output — two known ceilings: (1) a future blocker card whose TITLE contains the word READY false-unblocks this card (grep is not column-aware here); (2) the zero-open-prereq->READY transition was never observed on a flipping card (endpoints only) — trddgrep may never print READY after an archived blocker (known tooling gap). Treat a probe release as a PROMPT TO RE-VERIFY the chain, not proof of unblocked.
- 2026-10-09T05:31:52+0200 — column → todo. Same deadlock resolution as C30 (I4MOD020): the C22 dependency is a completion-event coupling — C32's Pass-1 run is C22's awaited evidence, so blocking C32 on C22 deadlocks the circle. Freeze treated as lifted (agent inference, owner may correct). C32 unblocked.
2026-10-09 dependency disposition (per the review on 6e450b80): the body 'Depends on: C22' is SATISFIED-THEN-COUPLED, not blocking — C22's code exists and C32's Pass-1 run is the evidence EVENT SHAPE C22's gate awaits, with the same evidence expectation as C30: on the present clean corpus a run has nothing to refuse; a zero-refusal outcome is the already-ruled clean-corpus case tracked by JD2QR5SQ's escalation clause (0 of 3), not a pending mystery. The work itself (shrink the enrich skill, same methodology as C31 with the cap re-measure) is unblocked and developable.
