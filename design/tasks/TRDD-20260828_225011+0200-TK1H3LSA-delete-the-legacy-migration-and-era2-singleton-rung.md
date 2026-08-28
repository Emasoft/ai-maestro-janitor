---
trdd-id: TK1H3LSA
title: Delete the legacy migration function and the era-2 singleton rung
column: backburner
blocked-by: []
created: 2026-08-28T22:50:11+0200
updated: 2026-08-28T22:50:11+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 7
severity: LOW
effort: S
min-approval-requirement: none
task-type: refactor
parent-trdd: TRDD-ULEGRT01
labels: [daemon, state-migration, cleanup]
release-via: publish
test-requirements: [unit]
---

# TRDD-TK1H3LSA — Delete `migrate_global_state_to_data_dir()` and the era-2 `_singleton_paths` rung

The one box TRDD-ULEGRT01 deliberately did not close. It carried the label "NEXT release" inside a
card that is otherwise finished, and a scheduled action living as an unchecked box on a done card
is how work stops being done — so it is its own card.

## What to delete, and the ONE precondition for each

Two independent deletions that happen to become safe at the same time. Do not treat them as one
edit; each has its own precondition, and the second is the one that bites.

1. **`migrate_global_state_to_data_dir()` + its sole call site (`daemon.py:2838`) +
   `_legacy_global_state_dir()`.**
   **Precondition:** every host has migrated. The function is the ONLY thing that carries a
   never-migrated host's state — kill-switch included — into the dir readers actually use, so
   deleting it early does not "clean up a no-op", it strands whatever is still in the legacy dir.
   Verify before deleting, do not assume: a host that has been offline for the whole retirement
   window is exactly the population this protects.

2. **The era-2 (`global-state`) rung in `_singleton_paths`, and with it `_old_global_state_path`
   from the six flag tuples.**
   **Precondition:** no pre-QK7M2B0X daemon can still start anywhere. This rung is the LOCK set,
   not a read list. Drop it while an old daemon can still run and the DATA dir's `daemon.flock`
   goes UNHELD — a second daemon takes it and runs alongside the current one — and the same edit
   blinds `foreign_era_daemons()` (`global_state.py:684`), the detector built to catch precisely
   that. The failure is silent and the detector for it is what you just removed.

## Gate (do NOT start before)

Extend TRDD-ULEGRT01's gate to the DATA path — it checked LEGACY only, so this half would ship
ungated. Add: no stop-class flag and no `armed.flag` at `<DATA>/global-state/`. Measured
2026-08-28: control_dir held `armed.flag` + `reload-needed.flag`; DATA and legacy held only
`reload-needed.flag`; no stop-class flag at any era. That measurement is a snapshot, not the gate
— **codify it as a runnable check, do not carry the number forward.**

## Also in scope, because it is the last era-1 reader

`safe_storage.py::_legacy_keychain_latch_path` (four call sites, ~lines 175/188/233/249) — the
read-only keychain latch, dropped from ULEGRT01 because retiring it risks a real macOS keychain
dialog to delete ~10 lines. Retire it here, and promote any existing legacy latch to the canonical
path in the same preflight, so a machine that already latched a denial does not re-open the
prompt-flood incident (see the `macos-keychain` wikimem page). Bounded either way
(`set_keychain_denied` latches canonically on first denial, and EQJPPZ2L's half-open cooldown caps
probes at one per 600 s ⇒ worst case ≈ one prompt per machine), but one file-move is cheaper than
one user-visible dialog.

## What must NOT change

`_flag_clear_dual` keeps sweeping every location a flag can live, INCLUDING the retired era-1 dir,
for as long as anything can copy from it. That asymmetry cost ULEGRT01 a real defect — a cleared
kill-switch resurrected by the migration — and it looks like an oversight to anyone tidying. See
TRDD-ULEGRT01's notes before touching it.

## Acceptance

- [ ] Gate extended to the DATA path and RUN (codified, not recalled).
- [ ] Deletion 1 with its precondition verified.
- [ ] Deletion 2 with its precondition verified.
- [ ] `_legacy_keychain_latch_path` retired, with the latch promoted first.
- [ ] The historical-migration tests in `tests/test_global_state_migration.py` retired with the
      function they cover; `test_clear_reaches_the_retired_dir_...` retired ONLY together with the
      migration, since it exists to prove the migration cannot resurrect a cleared flag.
- [ ] `uv run pytest` + `ruff` + `mypy` green. Budget bytes before editing any `rules/*.md`: the
      shipped-rules corpus sits within single-digit bytes of its floor cap by design.

## Notes and lessons learned

- 2026-08-28 — Spun out of TRDD-ULEGRT01 at its close. The parent's own lesson applies here twice
  over: **when you retire a READ path, audit the WRITE and DELETE paths separately** — "where I
  look" and "where I must not leave anything" are different questions.
