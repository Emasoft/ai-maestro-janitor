---
trdd-id: TVDK9Q1Y
title: Test-isolation guard cannot see session-heartbeat writes so the full suite always exits 3
column: cancelled
created: 2026-08-14T16:20:26+0200
updated: 2026-08-14T16:52:00+0200
current-owner: janitor-session
task-type: infra
project-id: ai-maestro-janitor
approval-tier: 0
npt: []
eht: []
implementation-commits: []
---

# The isolation guard cannot see session-heartbeat writes, so the full suite always exits 3

## ⏵ STATE — CANCELLED 2026-08-14. THE PREMISE WAS FALSE. READ THIS FIRST.

**There is no defect. The guard behaved correctly and there is no publish blocker.**
Everything below this block was written from a WRONG diagnosis and is retained only as
the audit trail; do not act on any of it.

**What actually happened.** The suite exited 3 because of a `source-tree` mutation —
`scripts/daemon.py`, `scripts/hooks/pre-compact-handoff.py`,
`scripts/lib/version_update_lib.py` were EDITED BY ME AND MY WORKERS while the
28-minute suite ran in the background. That is precisely the leak `source-tree` exists
to catch, reported exactly as designed.

The `plugin-data` / `usage-probe` writes I built this entire card on were printed under
the guard's own heading **"Also seen, attributed to the LIVE daemon (not counted as
failures)"**. They were correctly amnestied via `daemon_ticked` the whole time. The
witness machinery was never broken.

**ROOT CAUSE OF THE MISDIAGNOSIS — read this, it is the only durable value here.** I
diagnosed from `tail`. The guard prints its DIAGNOSIS header first and the
"also seen, not failures" detail LAST, so `tail -N` kept exactly the wrong end: I saw
the amnestied lines and never saw the `REAL-STATE WRITE GUARD FAILED … [source-tree]`
header 30 lines above. `~/.claude/rules/never-tail-on-error-messages.md` states this
exact failure ("programs print the DIAGNOSIS first and the raw underlying error last,
so `tail -N` keeps exactly the wrong end and you 'find' a defect the cut lines already
explained") and was loaded in context throughout. Cost: this card, an advisor
consultation with four addenda, and a multi-turn investigation with two refuted
hypotheses — all downstream of one truncation.

Two compounding errors worth naming separately, because each was independently
sufficient to mislead:
1. **Grepping for guesses instead of reading the output.** I grepped for an
   attribution header and treated its absence as proof. It proves nothing: line 915 is
   `if daemon_diffs and not diffs:`, so that header is SUPPRESSED whenever a hard diff
   also exists — which was exactly the case.
2. **Running the full suite while editing its guarded source tree.** A `source-tree`
   failure is guaranteed under those conditions. The operational rule is simply: do not
   run the full suite concurrently with source edits, and do not treat a run overlapping
   edits as evidence of anything.

**Residual, NOT a defect and NOT this card:** `_other_janitor_actor_live()`'s docstring
names three actors while its implementation probes two. That divergence is real but
LATENT — the amnesty here came from `daemon_ticked`, not from that probe. If it is ever
worth tightening, it needs its own card with its own evidence, not this one's.

<details><summary>Original (WRONG) premise, kept as audit trail</summary>

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

## MEASURED 2026-08-14 — two hypotheses REFUTED, mechanism still open

Recorded per the corpus lesson "file the reproduction as PROOF and the mechanism as an
explicitly labelled HYPOTHESIS" — a maintainer's static reading can reach a different
conclusion and argue with the mechanism instead of running the repro.

**✓ VERIFIED (facts, reproducible):**
- The daemon is ALIVE and ticking: `daemon.pid` = 90235, that pid is a live
  `daemon_keepalive_entry.py --keepalive` running 2d05h; `daemon.heartbeat.ts` 0.4 min old.
- `~/.aimaestro/server-liveness.json` is also fresh (0.4 min).
- `daemon.log` contains **zero** `server-owns-host` lines — the daemon never stood down.
- `daemon_ticked` is a PURE function over `(before, after)` snapshots; it does not resolve
  paths itself. `_ISOLATION_ENVS` captures the real env, and `conftest.py:177-189` records
  that the silent-env-probe class was already found and fixed TWICE for the server probe.

**✗ REFUTED HYPOTHESIS 1 — "the host was in the unowned/handover state."** It was not: a
live ticking daemon and a fresh server-liveness both existed, and nothing stood down. So
this is NOT the `janitor-daemon-handover-unowned-chores` override hole.

**✗ REFUTED HYPOTHESIS 2 — "`daemon_ticked` reads a monkeypatched env path and so sees no
daemon inside the test process."** It cannot: the function is pure and its inputs are
snapshotted from real paths.

**? OPEN (hypothesis, NOT established) — why the amnesty did not fire.** With a live
ticking daemon at both ends, `daemon_ticked` should be True, and the `usage-probe` amnesty
should have applied — yet run 2 flagged `usage-probe` alone. One of these is false and the
next session must determine WHICH before writing code:
  (a) `daemon_ticked` returned False for a reason not yet identified;
  (b) the `usage-probe` amnesty is not reached for that label/path in practice;
  (c) the mutation is classified under a label whose amnesty never covered it.
**Do not implement the witness work until this is answered** — a fix built on the wrong
one of these greens the suite without addressing the cause, which is the failure this card
was created to avoid.

**SCOPE GUARD (advisor):** this card must stay inside `tests/`. Any edit outside `tests/`
is the early signal that it has grown a production change, and the publish blocker then
stays red while that refactor happens.

## Notes

Surfaced while gating TRDD-ZM5LZ24Y. Advisor review located the docstring/implementation
divergence; verified first-hand in source before filing.

The class this belongs to is named in the corpus as `ATOM-4GQU-0C9J`: *a claimed chore
transfers the ACT to the server but not the BREADCRUMB, so every janitor feature triggered
by our own stamp goes dark on a server-owned host, invisibly.* The general cure is that
ownership evidence must belong to the actor that TAKES OVER, not the one that withdraws —
which is what `~/.aimaestro/server-liveness.json` already is. A sweep of other
breadcrumb-keyed features is real and worth its own card; it is explicitly NOT this one.

An evidence correction that applies to this card's own reasoning: `debug-a-timestamp-says-when-never-who`
means "mtime moved during the run ⇒ the heartbeat wrote it" is NOT valid. What survives is
(i) the non-determinism across identical runs, and (ii) mtimes advancing AFTER the run had
ended — which uses the timestamp only for WHEN and derives WHO by exclusion, the suite no
longer existing at that point. Note also that non-determinism alone does not exclude a RACY
test leak; the negative tests in the acceptance criteria are what carry the proof burden.

Related: `[[janitor-keepalive-test-isolation-fsevents]]` (the prior incident and its three
escaped isolation layers).

</details>
