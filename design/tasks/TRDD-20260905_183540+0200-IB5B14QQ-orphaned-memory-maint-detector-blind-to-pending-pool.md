---
trdd-id: IB5B14QQ
title: orphaned-memory-maint detector reads only the legacy slot and never the per-dispatch pending pool
column: testing
created: 2026-09-05T18:35:40+0200
updated: 2026-09-05T22:06:40+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-05

Implemented. `scripts/lib/orphaned_memory_maint.py` gained `read_record(path)` (the
same field-validation `read_pending` already did, generalized to any file path) and
`read_pending` is now a one-line wrapper over it. `scripts/detectors/orphaned-memory-maint.py`
gained `_evaluate_and_emit()` (the shared age/cadence/dedupe/ledger logic, factored
out of `main()`) and `_check_pool()` (enumerates `memory_dispatch_claim.candidates()`,
applies the same rule to each unclaimed per-dispatch record, dedupe key
`pool:<dispatch_id>` — unique per dispatch, so no forget-on-heal is needed there).
The legacy slot read stays: `memory-maintenance.py::_write_pending` still
`atomic_write`s it on every dispatch (line ~312) — grep confirmed, not dead code.
Pool check runs unconditionally, including when the legacy slot is itself malformed
(restructured `main()`'s malformed branch to an if/else instead of an early return,
so the pool is never skipped because of the legacy slot's state).

Tests added to `tests/test_orphaned_memory_maint.py`: the two acceptance-named tests
plus two extra regression tests (`test_claimed_pool_record_is_not_orphaned`,
`test_superseded_pool_record_is_not_orphaned`) proving a claimed/superseded record
(renamed out of `candidates()`'s glob) is never misread as orphaned.

Verified: `uv run pytest tests/test_orphaned_memory_maint.py -q` — 26 passed. `ruff
check`, `mypy scripts/ --ignore-missing-imports`, `pyright` on touched files — all
clean. Left at `column: dev` (not `testing`/`complete`) per this session's git-lock
constraint (another agent owns git right now) — no commit was made.

**2026-09-05T22:04 — committed in 028de468, column → testing. Measured against a COPY of
the real pool** (14 `memory-maint-pending-*` records, 21 claimed): the new detector emits
exactly ONE finding — `enrich` (LOCAL) dispatched 47.9h ago, cadence 24h, never re-fired —
a genuine orphan the legacy-slot-only detector could not see. The other 13, listed one by
one (2026-09-05T22:05, real factors DEFAULT_FACTOR=3 / LOCAL_FACTOR=1): **9 are NOT
current** (`pending_is_current` false — a later dispatch of the same key advanced
`last_run` past their `stamped_at`; pre-af6340a5 leftovers the supersede-by-rename now
prevents at the source) and **4 are current but below cadence × factor** (retro-lesson
PROJECT 51.5h < 72h, repair PROJECT 19.5h, atomize PROJECT 6.4h, split PROJECT 1.7h).
No record carries an unknown intervention name. Two facts the review fork raised, checked:
`candidates()` is a bare `PENDING_PREFIX*.json` glob with no age/chore filter (no hidden
records); the second `sys.path.insert` does not shadow `state`/`dedupe` (both resolve to
`scripts/lib`). Known ceiling, not fixed: a `pool:<dispatch_id>` dedupe key that fired
is only forgotten when its record is read healthy again, which never happens once the
record is claimed or pruned — the seen file keeps one dead line per past orphan, bounded
by dispatch volume.

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

- [x] `orphaned-memory-maint.py` enumerates per-dispatch pending records via
      `memory_dispatch_claim.candidates()` and applies the orphan
      age/cadence rule to each.
- [x] A new test (e.g.
      `tests/test_orphaned_memory_maint.py::test_orphan_finding_for_stale_per_dispatch_record`)
      creates a stale unclaimed `memory-maint-pending-<id>.json` and asserts
      the detector raises exactly one finding for it.
- [x] A new test asserts no duplicate finding is raised for the same
      dispatch id across two consecutive detector runs within one cadence
      window (e.g.
      `test_orphan_finding_not_duplicated_within_cadence_window`).
- [x] The legacy-slot read path is either exercised by an existing/updated
      test proving something still writes it, or removed as dead code —
      resolved by the `grep -rn 'memory-maint-pending.json' scripts` check
      named above. (kept — `memory-maintenance.py::_write_pending` still writes
      it on every dispatch; existing `test_orphaned_local_pending_alarms` etc.
      exercise it.)
