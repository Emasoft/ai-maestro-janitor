---
trdd-id: A8DRPZFM
title: S1+S2 — session-default test isolation, real-state write guard, frozen-path-constant guard test
column: todo
created: 2026-07-04T04:46:15+0200
updated: 2026-07-04T04:46:15+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 2
severity: HIGH
effort: M
task-type: infra
parent-trdd: TRDD-ZNN0UK5K
relevant-rules: []
release-via: publish
test-requirements: [unit, lint, typecheck]
labels: [test-isolation, fseventsd-plan]
---

# TRDD-A8DRPZFM — Test-state pollution safeguards (fseventsd plan S1+S2)

## The task

Executes S1+S2 of the ratified fseventsd-runaway plan (parent TRDD-ZNN0UK5K; plan file
`~/.claude/plans/glittery-hatching-shell.md`). The 39 GB fseventsd incident shipped because
test isolation was per-test/opt-in: a module capturing `Path.home()` at import escaped it
and the suite corrupted the REAL keepalive closure. These two safeguards would have caught
it on the first CI run; they prevent the CLASS, not the instance.

## Plan

- **S1a** — `tests/conftest.py`: a SESSION-scoped autouse fixture pointing `HOME`,
  `JANITOR_GLOBAL_STATE_DIR`, `JANITOR_DATA_DIR` at a per-session tmp tree for the WHOLE
  suite by default; a test needing real paths opts out explicitly. Extend the existing
  `_isolate_janitor_state` shape — read conftest first, do not duplicate.
- **S1b** — session-end guard: snapshot the real `~/.claude/janitor-global-state/` + real
  DATA dir (mtime+sha manifest) before the run; FAIL the suite if anything under them
  changed during it.
- **S2** — a guard test importing every `scripts/lib/*.py` + `scripts/*.py` asserting no
  module-level constant is a bare `Path.home()/…` used for writes (must go through a
  call-time resolver). Allow-list the one wrapped legit fallback
  (`launchd_keepalive._DATA_DIR`).

## Derived tasks

- Throwaway-branch proof: reintroduce a frozen `Path.home()` writer → S2 fails AND S1b
  fails; record the proof in the report, then drop the branch.
- Whitelist mechanism documented so a future legit constant doesn't just get added blind.

## Verification

- Full suite (12k+) stays green; `find ~/.claude/janitor-global-state -newermt <run-start>`
  is empty after a full run; the throwaway-branch proof shows both guards firing.
