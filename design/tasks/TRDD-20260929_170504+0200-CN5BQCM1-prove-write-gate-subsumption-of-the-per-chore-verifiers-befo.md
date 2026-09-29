---
trdd-id: CN5BQCM1
title: Prove write-gate subsumption of the per-chore verifiers before any txn-core retirement
column: backburner
status: tasked
created: 2026-09-29T17:05:04+0200
updated: 2026-09-29T17:07:13+0200
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
relevant-rules: [2, 13]
---

# Prove write-gate subsumption of the per-chore verifiers before any txn-core retirement

## Mandate (owner verdict B, 2026-09-29)

Four-letters form, verbatim: "B: prove it first". The write-gate-vs-chore-verifier subsumption ceiling (CURE-4 of XI10BA5D's step-C post-commit review: verify_repair/verify_atomize/verify_merge byte-identity proofs are NOT proven covered by the gate's id-set rule) is NOT accepted as-is: a proof must enumerate every per-chore verifier's checks and show the memgrep write gate covers each BEFORE any transaction-core retirement. The txn page-writing machinery stays until this proof lands. Parent XI10BA5D; this card is the structured disposition of that ceiling — not accepted, scheduled for proof.

## Scope

Read the txn-core verify_* functions, the memgrep pre_write.rs id-set rule + write_gate_floors, produce a per-verifier coverage matrix (covered / partially-covered / gap), and propose dispositions for each gap (a gate rule, a kept verifier, or an owner question). NOT in scope: actually retiring the txn core (a later card once the proof passes).

## Approval log

- 2026-09-29T17:05:04+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
