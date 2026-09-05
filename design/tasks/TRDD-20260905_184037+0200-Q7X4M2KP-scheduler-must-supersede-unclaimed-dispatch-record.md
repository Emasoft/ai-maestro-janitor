---
trdd-id: Q7X4M2KP
title: Scheduler must supersede its own unclaimed dispatch record for the same scope root and intervention instead of stacking a new one
column: todo
created: 2026-09-05T18:40:37+0200
updated: 2026-09-05T18:40:37+0200
current-owner: main-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
npt: []
eht: []
external-refs: [github:Emasoft/ai-maestro-janitor#300]
---

## Symptom

`scripts/detectors/memory-maintenance.py:256 _write_pending` never supersedes an older
unclaimed record for the same `(scope, root, intervention)` key — the only bound is
`_PENDING_KEEP = 20` (line 197, prune at 238-251). `scripts/memory_dispatch_claim.py:70`
sorts candidates oldest-first and `claim_one` (line 110) claims the OLDEST — so every new
fire's record joins the pile while agents work the stalest dispatch first.

Measured on this host 2026-09-05: 4 unclaimed `split` records for the SAME PROJECT root
(10, 15, 34, 46 h old) and 2 unclaimed records for the USER root (34, 46 h old).

## Fix requirement

At `_write_pending` time, before writing the new record: find any unclaimed record with the
same `(scope, root, intervention)` key already in the pool and remove it from the pending
pool (rename with a `memory-maint-superseded-<id>.json` prefix, or unlink — pick one and say
why in the implementation commit) before the new record lands. This bounds the pool to at
most one pending record per key, so `claim_one`'s oldest-first pick can no longer hand out
stale, duplicate work for a key that has since been re-dispatched.

This also restores the intent of TRDD-LDSCQ0NU's relay-suppression gate: with duplicates
present in the pool, that gate always finds *some* match for the key and never actually
suppresses a redundant relay; with at most one record per key it becomes meaningful again.

## Acceptance criteria

- [ ] `_write_pending` removes (renames or unlinks) any existing unclaimed record sharing
      `(scope, root, intervention)` with the new record, before writing the new one.
- [ ] A new test in `tests/test_memory_maintenance.py` (e.g.
      `test_write_pending_supersedes_older_unclaimed_same_key`) seeds two unclaimed pending
      records for the same key at different ages, calls `_write_pending` again for that key,
      and asserts exactly one pending record for that key remains afterward.
- [ ] A new test asserts a CLAIMED record for the same key is left untouched (only unclaimed
      records are superseded).
- [ ] `uv run pytest tests/test_memory_maintenance.py -k supersede` passes.
- [ ] Full suite still green: `uv run pytest`.

## Notes

Filed as the follow-on to TRDD-N1CPV1QV (agent-side state-dir mismatch) and TRDD-IB5B14QQ
(detector blind to the pending pool) — this card is the third, scheduler-side leg: even once
the agent looks in the right directory and the detector can see the pile, the pile itself
keeps growing unless the scheduler stops stacking duplicate unclaimed records.

## Approval log
