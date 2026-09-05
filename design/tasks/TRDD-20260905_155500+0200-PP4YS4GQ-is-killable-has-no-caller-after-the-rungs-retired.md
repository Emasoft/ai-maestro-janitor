---
trdd-id: PP4YS4GQ
title: is_killable has no caller after the rungs retired
column: backburner
created: 2026-09-05T15:55:00+0200
updated: 2026-09-05T15:55:00+0200
current-owner: main-session
task-type: refactor
priority: low
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
external-refs: [TRDD-V07NFXS9, TRDD-56d24c02]
---

# `is_killable` has no caller after the rungs retired

## Why

TRDD-V07NFXS9 retired `build_force_restart`/`build_resurrect` (the only two rungs that
ever killed a pid) and their sole caller of `is_killable`
(`daemon.py::_run_hard_restart`). Per the card's explicit instruction, `is_killable()` in
`scripts/lib/fleet_restart.py` was **kept, not deleted** — it is one of the three safety
invariants TRDD-56d24c02 named as load-bearing regardless of rung retirement.

Grep evidence (`grep -rn "is_killable" scripts tests skills commands hooks docs
README.md --exclude-dir=target`, 2026-09-05):

```
scripts/lib/fleet_recovery.py:70:    execution on ``fleet_restart.hard_restart_enabled()`` (DEFAULT-OFF dry-run) + ``is_killable``,
scripts/lib/fleet_restart.py:16:with a safety story attached. ``hard_restart_enabled()`` and ``is_killable`` are
scripts/lib/fleet_restart.py:18:rungs) even though this module no longer calls ``is_killable`` itself.
scripts/lib/fleet_restart.py:141:def is_killable(
tests/test_fleet_restart.py:7:`is_killable`'s own refusal gate (kept per TRDD-56d24c02's decision even though this
tests/test_fleet_restart.py:33:    """Shape of `is_killable`'s kwargs (TypedDict, PEP 692) — a bare `dict(...)` mixing
tests/test_fleet_restart.py:58:def test_is_killable_refuses_everything_but_a_wedged_claude() -> None:
tests/test_fleet_restart.py:69-76:    (direct-call assertions on `fn.is_killable(...)`)
```

Every non-test hit is a comment referencing it or the definition itself — no `scripts/`
production code calls it. Its only remaining callers are its own unit tests
(`tests/test_fleet_restart.py`), which exercise the function directly, not through any
live daemon path.

## Decision needed

Delete `is_killable()` (and its direct-call test) as now-genuinely-dead code, OR keep it
as an exported safety primitive on the theory that a future hard-kill rung (should
TRDD-56d24c02's `decision:user` ever authorize one) would need it and re-deriving the
exact refusal logic from scratch is the riskier path. TRDD-V07NFXS9 deliberately left
this open rather than deciding it inline.

## Notes and lessons learned
