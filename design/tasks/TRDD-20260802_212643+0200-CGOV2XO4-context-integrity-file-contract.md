---
trdd-id: CGOV2XO4
title: Write the context-integrity file the ai-maestro wake gate reads
column: todo
created: 2026-08-02T21:26:43+0200
updated: 2026-08-02T21:26:43+0200
current-owner: janitor-session
task-type: feature
severity: medium
scope: project
release-via: publish
external-refs: [167]
implementation-commits: []
---

# Context-integrity file contract — janitor writes, ai-maestro server reads (janitor#167)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Not started.** Filed from the ai-maestro Claude's design decision on janitor#167
(2026-08-02): the previously-blocking "CLI flag for contextPoisoned" is WITHDRAWN by its
owner — a refuse-a-wake verb is a denial-of-service primitive with no expressible
authorization (the janitor's scripts carry no AID), so the server side replaced it with a
FILE contract, the proven `server-liveness.json` pattern INVERTED:

- **`~/.aimaestro/context-integrity.json`** — the JANITOR writes, the SERVER reads.
- Shape (from the peer's comment; confirm the final schema on the issue before building):
  `{ "ts": <epoch-s>, ... }` plus the per-workdir poisoned reason.
- The janitor side is thin: `scripts/detectors/agent-context-integrity.py` ALREADY
  computes `poisoned_reason(findings, cap)` — "The contextPoisonedReason string for the
  ai-maestro wake gate (janitor#167)". What is missing is only the atomic write of the
  file (bounded, per-workdir, ts-stamped, atomic_write; clear/refresh semantics so a
  healed workdir stops being blocked — a stale poisoned claim is itself a DoS).

## Steps

1. Read janitor#167's full thread for the final agreed schema (the peer names the file
   and the inversion; nail field names + staleness window + multi-workdir keying).
2. Reply consensus on the issue BEFORE building (peer-consensus rule) — done at filing
   time; re-confirm if the schema moved.
3. Implement the write in agent-context-integrity.py (atomic, fail-open, self-clearing);
   pin with tests incl. the heal-clears-the-claim direction and the staleness bound.

## Verification

- Poisoned scan ⇒ the file appears with the reason + fresh ts; healed scan ⇒ the claim
  clears; a stale file past the agreed window is ignorable by the server (ts present).

## Notes and lessons learned
