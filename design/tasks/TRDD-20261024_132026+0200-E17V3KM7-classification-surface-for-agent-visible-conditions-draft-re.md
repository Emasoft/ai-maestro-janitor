---
trdd-id: E17V3KM7
title: Classification surface for agent-visible conditions (draft revision 3)
column: design
status: tasked
created: 2026-10-24T13:20:26+0200
updated: 2026-10-24T13:23:12+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-24T13:20:26+0200
parent-trdd: F3LVCQ39
---

# Classification surface for agent-visible conditions (draft revision 3)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-24
Draft revision 3 of the classification surface that TRDD-F3LVCQ39 acceptance items 2, 5 and 6 require. Revisions 1 and 2 each had a measurement and an adversarial review and were found not ready (recorded in the STATE block of TRDD-F3LVCQ39). This draft is UNREVIEWED and NOT APPROVED: do not build from it. OWNER QUESTION: the turn protocol caps proposal review at two rounds, so whether this draft gets a third round or is built without one is the owner's call. NEXT: on the owner's answer, run the third round or start increment 1. Evidence for the closures below: reports/board/20261024_131820+0200-F3LVCQ39-open-holes.md (gitignored; a read-only worker's report, ✓ marks are its own unless noted as re-read).

## Design (draft)

1. KEY. A condition is classified by the pair (the dispatcher's own detector-name argument `name` in scripts/dispatch.py `_run_detector`, a registered issue code or none). The name printed in a line and the `emitter` field of design/specs/issue-codes.toml are never used as the key.
2. CODE POSITION. A code counts only when the first line of a block matches, at column 0, `^(?:\[(?P<det>[a-z0-9-]+)\]|\[ticket\]) (?P<code>[A-Z][A-Z0-9]*-\d{3})(?=[ \t]|$)`, `det` equals `name` in the bracket form, and the code is registered. Re-read ✓: state.sanitize_for_drift_line turns every `[` and `]` into look-alike brackets (scripts/lib/state.py:1407), so text that passed through it cannot forge a header. OPEN: a detector that prints third-party text at column 0 without that sanitizer; enumerate the print sites before building.
3. BLOCKS. A block starts at a column-0 header `[<name>]` or `[ticket]`; every following line that starts no block joins it; lines before the first header form a block with no code. A bare `[janitor-...]` marker line is its own block, is never classified, and stays with the heartbeat protocol. The class of a block is computed once, on the raw text, right after `_exclude_control_plane_output` and before the defang step and the filters; continuation lines inherit it and can never lower it.
4. TRANSPORT. Split the raw output into blocks, concatenate the blocks of each class in order, and run the existing filter chain once per class group. The dedupe summary line takes AGENT-ACTIONABLE. OPEN: the suppressed-count state file is keyed by detector name and must not be overwritten by two groups of one fire; a test must show it. OPEN: grouping reorders output across classes, so a headline and a related line of another class lose adjacency; `_drop_ticketed_blocks` treats the whole output up to the trailing ticket-key marker as one block, and its place in the chain relative to the grouping is not yet traced; when the dedupe drops a headline but keeps its continuation, the orphan keeps its class but loses its context.
5. TABLE. A separate per-condition table under scripts/lib, keyed (detector, code or none), giving a class plus the owner's remedy for OWNER-ONLY or the decider for UNCLASSIFIED. A FAIL_OPEN sentinel, distinct from the class AGENT-ACTIONABLE, marks an explicit entry that the lookup treats as a miss. design/specs/issue-codes.toml and its generator stay untouched.
6. TICKET CODES. A table entry for (detector, code) always wins; only when none exists does a `[ticket]` block take a DEFAULT class from the code's kind through scripts/lib/tickets.py KIND_REGISTRY (re-read ✓ :68-80): a HARNESS kind with dispatch on maps to INFORMATIONAL, because its line says the janitor repairs it itself and the action reaches the agent as the separate `[janitor-ticket]` marker; a PROJECT kind maps to OWNER-ONLY, because its line asks a human to approve a fix (scripts/lib/issue_catalog.py:417 ✓); memory-corpus (dispatch off) maps to FAIL_OPEN. The HARNESS default is not enough for self-integrity: the census classes janitor-self-integrity rows A69-A72 OWNER-ONLY (rows the merged-census review checked in code; ? a re-pin may need the owner), so the SELFINT codes need OWNER-ONLY table entries in increment 1; any other HARNESS kind with an OWNER-ONLY census row gets the same treatment in increment 2, after the census rows are corrected and checked in code. A test asserts the mapping covers every key of KIND_REGISTRY. 37 of the 90 registered codes carry a kind (✓ grep count); the other 53 need a table entry or fail open.
7. COVERAGE. Every detector whose output or ledger rows can reach a model turn, advisory ones included, has an explicit entry (a class or FAIL_OPEN). The dispatcher's own default is AGENT-ACTIONABLE. Multi-class detectors with any OWNER-ONLY census row get their codes in increment 2; that set is computed only after the census rows are corrected and each OWNER-ONLY row is checked in code.
8. TESTS, each able to fail: an unknown source returns AGENT-ACTIONABLE; the explicit-entry coverage set is computed from `_DETECTORS` at test time; a code outside the anchored position is not honored; a `[<other>]` header inside `name`'s output is not honored; a continuation line inherits its block's class; the kind mapping covers KIND_REGISTRY; no recorded OWNER-ONLY condition resolves to any lower class (AGENT-ACTIONABLE or INFORMATIONAL), the SELFINT codes included.
9. INCREMENTS, one commit each: (1) table, lookup, block split, tests and a few seed entries; (2) census-corrected defaults and codes for the multi-class detectors with OWNER-ONLY rows; (3) codes for the remaining multi-class detectors (each changed line shows once more on the day it ships, because the daily dedupe keys on the line text).
10. OUT OF SCOPE: what a class triggers (TRDD-5CGPEK4V), the ledger line shape, design/specs/issue-codes.toml.

## Side finding, candidate for its own card
`_drop_suppressed_lines` (scripts/dispatch.py:1025-1045, re-read ✓) takes the first registered code ANYWHERE in a line with `.search`, so a registered LOW or MEDIUM code inside third-party text in an unrelated line could drop that line if the owner suppressed that code. Mechanism ✓; exploitability ? (needs an owner suppression of that exact code).

## Approval log

- 2026-10-24T13:20:26+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
