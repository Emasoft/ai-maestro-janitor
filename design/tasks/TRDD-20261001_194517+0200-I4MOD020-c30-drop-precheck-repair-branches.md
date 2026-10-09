---
trdd-id: I4MOD020
title: C30 — drop precheck repair branches
column: todo
status: tasked
created: 2026-10-01T19:45:17+0200
updated: 2026-10-09T05:34:55+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:17+0200
blocked-by: []
pre-block-column: todo
blocker-probe: [trddgrep, why, I4MOD020]
blocker-holds-if: not-match:READY
---

# C30 — drop precheck repair branches

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C30, wave W3.

Writes (exclusive): scripts/lib/memory_content_precheck.py, its tests
Task: Drop repair_defect branches whose defect now has a SAFE fixer
Verify: A fixture run through memgrep lint, then the predicate, finds no SAFE-class defect
Depends on: C22
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:15+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on JD2QR5SQ per DSN035UN wave order
- 2026-10-08 (probe caveat, corpus sweep): this why-probe's holds-if is not-match:READY against trddgrep why output — two known ceilings: (1) a future blocker card whose TITLE contains the word READY false-unblocks this card (grep is not column-aware here); (2) the zero-open-prereq->READY transition was never observed on a flipping card (endpoints only) — trddgrep may never print READY after an archived blocker (known tooling gap). Treat a probe release as a PROMPT TO RE-VERIFY the chain, not proof of unblocked.
- 2026-10-09T05:31:42+0200 — column → todo. JD2QR5SQ's dependency shape is a completion-event coupling, not a hard blocker: C22's gate needs a DEPENDENT to run Pass 1 on a real root — C30 IS that dependent, so blocking C30 on C22 completes a recorded deadlock (found by the verification review on 49261c98). The freeze is treated as lifted (agent inference, owner may correct). C30 unblocked; its own Pass-1 run is C22's awaited evidence.
2026-10-09 dependency disposition (per the review on 6e450b80): the body 'Depends on: C22' is SATISFIED-THEN-COUPLED, not blocking — C22's code exists (installed binary 4ecdbc3 carries S1-S4) and the coupling is that C30's Pass-1 run is the evidence EVENT SHAPE C22's gate awaits. Evidence expectation corrected: on the present corpus (measured 2026-10-09, zero fixer-backed findings on all three real roots) a Pass-1 run here has nothing to refuse — a zero-refusal outcome is the already-ruled clean-corpus case, tracked by the escalation clause on JD2QR5SQ (count 0 of 3 memory-repair dispatches), NOT a pending mystery. The work itself (dropping precheck repair branches with SAFE fixers) is unblocked and developable.
