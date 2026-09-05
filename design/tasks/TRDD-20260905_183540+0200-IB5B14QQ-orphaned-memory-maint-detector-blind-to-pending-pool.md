---
trdd-id: IB5B14QQ
title: orphaned-memory-maint detector reads only the legacy slot and never the per-dispatch pending pool
column: todo
created: 2026-09-05T18:35:40+0200
updated: 2026-09-05T18:42:00+0200
current-owner: main-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
npt: []
eht: []
external-refs: [github:Emasoft/ai-maestro-janitor#300]
---

# orphaned-memory-maint detector reads only the legacy slot and never the per-dispatch pending pool

## Symptom

See also TRDD-Q7X4M2KP — this card makes the pile of unclaimed per-dispatch records
visible; Q7X4M2KP stops the scheduler from growing that pile in the first place.

`scripts/detectors/orphaned-memory-maint.py:63` reads ONLY the legacy
single-slot file `memory-maint-pending.json` (`omm.read_pending`,
`PENDING_NAME`). It never enumerates the per-dispatch pool
(`memory-maint-pending-<id>.json`, one file per dispatch, written by
`memory-maintenance.py::_write_pending`). Measured on this host 2026-09-05:
14 unclaimed per-dispatch records existed (6 `split`, 10-46h old) and were
completely invisible to this detector — no orphan finding was ever raised
for them.

## Fix requirement

- The detector enumerates `memory-maint-pending-*.json` via
  `memory_dispatch_claim.candidates()` (the existing shared enumerator —
  do not re-implement globbing/parsing).
- Applies the same age x cadence orphan rule to each per-dispatch record
  that it currently applies to the legacy slot.
- Emits one finding per orphaned record, deduped (no duplicate finding for
  the same dispatch id across repeated detector runs within one cadence
  window).
- Keep reading the legacy slot ONLY if something still writes it — verify
  with `grep -rn 'memory-maint-pending.json' scripts` before deciding
  whether to keep or drop that branch; if nothing writes it any more, drop
  the legacy-slot read entirely rather than keeping dead code.

## Acceptance criteria

- [ ] `orphaned-memory-maint.py` enumerates per-dispatch pending records via
      `memory_dispatch_claim.candidates()` and applies the orphan
      age/cadence rule to each.
- [ ] A new test (e.g.
      `tests/test_orphaned_memory_maint.py::test_orphan_finding_for_stale_per_dispatch_record`)
      creates a stale unclaimed `memory-maint-pending-<id>.json` and asserts
      the detector raises exactly one finding for it.
- [ ] A new test asserts no duplicate finding is raised for the same
      dispatch id across two consecutive detector runs within one cadence
      window (e.g.
      `test_orphan_finding_not_duplicated_within_cadence_window`).
- [ ] The legacy-slot read path is either exercised by an existing/updated
      test proving something still writes it, or removed as dead code —
      resolved by the `grep -rn 'memory-maint-pending.json' scripts` check
      named above.
