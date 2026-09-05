---
trdd-id: Q7X4M2KP
title: Scheduler must supersede its own unclaimed dispatch record for the same scope root and intervention instead of stacking a new one
column: todo
created: 2026-09-05T18:40:37+0200
updated: 2026-09-05T18:55:16+0200
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

## Mechanism

This is NOT a missing dedupe of independently-arriving duplicate requests. It is what
happens when `global_state.memory_root_inflight()` (`scripts/lib/global_state.py:1114`,
`MEMORY_INFLIGHT_TTL_S = 30 * 60`, fail-open) times out without ever being claimed: the
30-minute in-flight stamp lapses, the scheduler's next pass (`memory-maintenance.py:592-599`
returns early only while the stamp is live) writes a fresh pending record for the same key,
and the old one is left behind because `_write_pending` never looks for it. A second, distinct
path to the same pile-up: `memory_root_inflight()` (`scripts/lib/global_state.py:1142-1157`)
fails OPEN on an unreadable/corrupt stamp — it returns `None` — so a fresh pending record can
also be written WITHOUT the 30-minute TTL ever lapsing (V3). Both paths land in the same place:
an unclaimed record for a key that already has one. Card N1CPV1QV
(agent-side state-dir mismatch) explains why a spawned agent can fail to claim the record at
all; card IB5B14QQ makes the resulting pile visible to the scheduler. This card is the third
leg: even once an agent looks in the right directory and the pile is visible, the pile keeps
growing on every lapsed TTL unless the scheduler stops stacking a duplicate record per lapse.

## Fix requirement

At `_write_pending` time, before writing the new record: find any unclaimed record with the
same `(scope, root, intervention)` key already in the pool and remove it from the pending
pool by RENAMING it to a `memory-maint-superseded-<id>.json` prefix (never unlink — keep the
superseded record inspectable for audit) before the new record lands. This bounds the pool to
at most one pending record per key, so `claim_one`'s oldest-first pick can no longer hand out
stale, duplicate work for a key that has since been re-dispatched.

The rename-based supersede is race-safe against a peer claiming the record concurrently:
`memory_dispatch_claim.py::claim_one` (`scripts/memory_dispatch_claim.py:110`) wraps its own
`os.rename(path, target)` claim attempt in `try … except OSError: continue`, so a peer that
loses the race to the scheduler's supersede-rename simply moves on to the next candidate
instead of erroring. Do not remove or narrow that except clause.

This also restores the intent of TRDD-LDSCQ0NU's relay-suppression gate: with duplicates
present in the pool, that gate always finds *some* match for the key and never actually
suppresses a redundant relay; with at most one record per key it becomes meaningful again.

The new `memory-maint-superseded-` prefix joins the prune tuple at `memory-maintenance.py:238`
under the same `_PENDING_KEEP` cap: today that prune loop only walks `(_PENDING_PREFIX,
_CLAIMED_PREFIX)`, so a third, un-pruned prefix would accumulate one file per lapse forever.

## Acceptance criteria

- [ ] `_write_pending` removes (renames or unlinks) any existing unclaimed record sharing
      `(scope, root, intervention)` with the new record, before writing the new one.
- [ ] A new test in `tests/test_memory_maintenance.py` (e.g.
      `test_write_pending_supersedes_older_unclaimed_same_key`) seeds two unclaimed pending
      records for the same key at different ages, calls `_write_pending` again for that key,
      and asserts exactly one pending record for that key remains afterward.
- [ ] A new test asserts a CLAIMED record for the same key is left untouched (only unclaimed
      records are superseded).
- [ ] A new test pins the `claim_one` `except OSError: continue` behavior against a record
      concurrently renamed out from under it by a supersede (the peer-claim race stays benign).
- [ ] `uv run pytest tests/test_memory_maintenance.py -k supersede` passes.
- [ ] Full suite still green: `uv run pytest`.
- [ ] A new test seeds `_PENDING_KEEP + N` superseded lapses for distinct keys and asserts the
      `memory-maint-superseded-` count never exceeds `_PENDING_KEEP` after the prune pass runs.

## Notes

Filed as the follow-on to TRDD-N1CPV1QV (agent-side state-dir mismatch) and TRDD-IB5B14QQ
(detector blind to the pending pool) — this card is the third, scheduler-side leg: even once
the agent looks in the right directory and the detector can see the pile, the pile itself
keeps growing unless the scheduler stops stacking duplicate unclaimed records.

## Approval log
