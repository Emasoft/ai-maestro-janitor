---
trdd-id: CN5BQCM1
title: Prove write-gate subsumption of the per-chore verifiers before any txn-core retirement
column: backburner
status: tasked
created: 2026-09-29T17:05:04+0200
updated: 2026-09-29T17:20:46+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: audit
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-09-29T17:05:04+0200
parent-trdd: XI10BA5D
relevant-rules: []
---

# Prove write-gate subsumption of the per-chore verifiers before any txn-core retirement

## Mandate (owner verdict B, 2026-09-29)

Four-letters form, verbatim: "B: prove it first". The write-gate-vs-chore-verifier subsumption ceiling (CURE-4 of XI10BA5D's step-C post-commit review: verify_repair/verify_atomize/verify_merge byte-identity proofs are NOT proven covered by the gate's id-set rule) is NOT accepted as-is: a proof must enumerate every per-chore verifier's checks and show the memgrep write gate covers each BEFORE any transaction-core retirement. The txn page-writing machinery stays until this proof lands. Parent XI10BA5D; this card is the structured disposition of that ceiling — not accepted, scheduled for proof.
REVIEW DISCHARGE (fork 2026-09-29): (1) eht wiring REMOVED — the proof gates RETIREMENT, not this card's close; parent-trdd XI10BA5D is the only link (publish pipeline must not stall on a backburner audit). (2) relevant-rules [2,13] CLEARED — the numbers were invented; no PRRD read preceded the mint. A future pass reads the PRRD and sets real numbers or leaves the field empty.
STRUCTURED PULL (second-review F1, 2026-09-29): if a txn-core-retirement card is minted before this proof lands, that card MUST wire npt: CN5BQCM1 — recorded HERE on this card because its own trdd-drift resurfacing (backburner is drift-eligible by default) is the one live mechanism that will actually surface the obligation; XI10BA5D's STATE carries the same order as history, but this card is the operative location.
SCOPE OF THAT GUARANTEE (final-review F1, 2026-09-29): drift resurfacing is eventually-visible, NOT mint-time-gating — it may surface this card long after a retirement card shipped. The mint-time path relies on the minter reading XI10BA5D's history; this is accepted as the best available structure short of an eht.

## Scope

Read the txn-core verify_* functions, the memgrep pre_write.rs id-set rule + write_gate_floors, produce a per-verifier coverage matrix (covered / partially-covered / gap), and propose dispositions for each gap (a gate rule, a kept verifier, or an owner question). NOT in scope: actually retiring the txn core (a later card once the proof passes).

## Approval log

- 2026-09-29T17:05:04+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
