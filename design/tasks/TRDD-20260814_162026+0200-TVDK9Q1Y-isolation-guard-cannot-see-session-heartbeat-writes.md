---
trdd-id: TVDK9Q1Y
title: Test-isolation guard cannot see session-heartbeat writes so the full suite always exits 3
column: todo
created: 2026-08-14T16:20:26+0200
updated: 2026-08-14T16:20:26+0200
current-owner: janitor-session
task-type: infra
project-id: ai-maestro-janitor
approval-tier: 0
npt: []
eht: []
implementation-commits: []
---

# The isolation guard cannot see session-heartbeat writes, so the full suite always exits 3

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-14

- **This is a PUBLISH BLOCKER.** `scripts/publish.py` runs the full suite as a gate.
  The suite exits 3 on any armed developer machine, so nothing can publish from here
  until this is fixed.
- **NEXT ACTION:** extend `_other_janitor_actor_live()` in `tests/conftest.py` with
  provenance witnesses for the two actors its own docstring already names but never
  probes (see "The gap" below).
- **DO NOT** fix this by adding filename exclusions. That is the documented failure of
  the previous incident, recorded in the wikimem page
  `janitor-keepalive-test-isolation-fsevents`: `.log` and `.restage-stamp` were excluded
  as "daemon liveness churn", and those were exactly the two files the real incident
  wrote, so the detector was blind to its own incident. **An exclusion added to silence
  noise must be interrogated for the failure class it makes invisible.**

## Evidence

Two full-suite runs, same code, same suite:

| | run 1 | run 2 |
|---|---|---|
| tests | 15339 passed, 1 skipped | 15339 passed, 1 skipped |
| exit | 3 | 3 |
| flagged | `oauth-usage-cooldown.json`, a USER memory page, `usage-probe/…json` | `usage-probe/…json` only |

**The differing sets are the proof.** Test pollution is deterministic — the same tests
writing the same real paths would flag the same files every run. A set that varies with
wall-clock implicates an actor outside the suite whose activity depends on what fired
during the window.

Corroborating: the three files' mtimes were 0.7 / 6.7 / 19.8 minutes old at inspection,
i.e. still being written AFTER the 27-minute run had ended.

Ruled out — the prior incident is dormant, not recurring: `daemon-keepalive.boot.log`
does contain 296 pytest-tmp-dir lines, but its mtime is **2026-08-05**, and its first and
last such lines are `test_corrupt_stage_is_restaged0` / `test_missing_file_is_restaged_0`
— the original incident's residue. The syscall-level refusal is holding.

## The gap (verified in source)

`tests/conftest.py::_other_janitor_actor_live()`.

Its **docstring** (`:155-162`) names three legitimate non-suite actors:
1. an ai-maestro server that claims the host,
2. *"several Claude sessions [that] run heartbeats that write the shared attribution cache"*,
3. *"the memory subconscious agent [that] edits USER-scope wiki pages"*.

Its **implementation** (`:188-204`) probes exactly two things: `~/.aimaestro/server-liveness.json`,
and `_daemon_witness(*roots)`.

So actors 2 and 3 — named in its own docstring as correct behaviour — are never probed.
With no ai-maestro server on the host and no daemon witness in the window, both checks
return False, and a legitimate heartbeat write is scored as a test leak.

This is a check whose SCOPE is narrower than the INVARIANT it guards, reporting a
failure it could never have attributed correctly.

## Why this matters more than one red gate

A suite for a product that is **by design always running** must be attributable under
load. Requiring a quiet host to get a green run is not a workable contract: it trains
everyone to read exit 3 as noise, and the day it means something nobody will look. That
is the same erosion the previous incident's exclusion caused, arrived at from the other
direction.

## Acceptance criteria

- [ ] `_other_janitor_actor_live()` gains a provenance witness for a live session
      heartbeat (e.g. a heartbeat stamp advancing across the run window).
- [ ] Same for the memory subconscious agent (e.g. a memory-transaction marker
      advancing), covering actor 3 from its own docstring.
- [ ] Witnesses are **provenance-based, never filename-based**. No entry is added to any
      exclusion list. A reviewer must be able to state which failure class each new
      witness makes invisible, and be satisfied it is none.
- [ ] A full `uv run pytest` exits 0 on this machine with the janitor ARMED and firing.
- [ ] A test proving the guard STILL trips when a genuine test-side write happens with no
      live actor — i.e. the fix must not be a blanket amnesty. This is the box that stops
      this card from becoming the next incident.
- [ ] `uv run ruff check scripts tests` and `uv run mypy scripts/ --ignore-missing-imports` clean.

## Notes

Surfaced while gating TRDD-ZM5LZ24Y. Advisor review located the docstring/implementation
divergence; verified first-hand in source before filing.

Related: `[[janitor-keepalive-test-isolation-fsevents]]` (the prior incident and its three
escaped isolation layers).
