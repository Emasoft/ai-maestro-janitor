---
trdd-id: IEW2K659
title: The documented detector roster names 39 of 72 detectors — a silently rotting inventory
column: todo
created: 2026-08-14T20:06:06+0200
updated: 2026-08-14T20:06:06+0200
current-owner: janitor-session
task-type: docs
project-id: ai-maestro-janitor
approval-tier: 0
severity: medium
npt: []
eht: []
implementation-commits: []
---

# The documented detector roster names 39 of 72 detectors

## The defect (MEASURED 2026-08-14, not estimated)

The PROJECT wikimem page `janitor-detector-and-hook-roster` documented **39**
detectors. `scripts/dispatch.py` registers **72**.

Measured by counting the registration entries themselves — the
`("name", cadence, "CLAUDE_PLUGIN_OPTION_…")` tuples in `dispatch.py` — not by
counting files, because a file in `scripts/detectors/` that nothing registers does
not run and should not be rostered. Both counts agreed at 72 here, but the
registration site is the authoritative one.

So **33 detectors — nearly half the fleet — are undocumented**. The COUNT has been
corrected in place via the supersede protocol (the old figure survives as a dated
`SUPERSEDED BODY`, never deleted). What remains is the grouped list itself.

## Why this rotted without anyone noticing

**An inventory has no test.** Every other claim in this repo is defended by
something that reddens: a wrong type fails mypy, a wrong behaviour fails pytest, a
wrong lint config fails ruff. A prose list of 39 things, in a file nothing
executes, cannot fail — it simply drifts, one un-updated addition at a time, while
continuing to read as authoritative.

That is the same failure class as a card with zero acceptance boxes, and as a guard
whose refusal branch no test reaches: **the absence of a failure signal is being
mistaken for the absence of a defect.**

The immediate trigger was TRDD-HK7IZ21Z adding a 40th-or-so detector and its design
naming "detector-roster update" as a derived task. Checking that one addition
surfaced a drift of 33.

## The fix

Reconcile the grouped roster against `dispatch.py`'s registration list. For each
missing detector: which group, what it does in one line, and its cadence/default.
The existing groups (git/workflow hygiene, TRDD/task, cleanup, observability, scope
drift, supply-chain/security, updates) are still CORRECT about the detectors they
name — they are incomplete, not wrong, so this is an additive pass and no existing
entry needs superseding.

This is editorial work on the shared corpus at PROJECT scope, so it belongs to the
memory curator (`janitor-memory-subconscious-agent`), not to a code worker.

## Acceptance criteria

- [ ] Every detector registered in `dispatch.py` appears in the grouped roster.
- [ ] The count is DERIVED and stated with its measurement method, so the next
      reader can re-check it in one command rather than trusting the number.
- [ ] `system-daemon-runaway` (TRDD-HK7IZ21Z) is in the observability group.
- [ ] Something makes the next drift VISIBLE. A prose count that only a human can
      falsify will rot again — the whole point of this card. Prefer a check that
      compares the rostered names against `dispatch.py`'s registrations and reports
      the difference, so the inventory acquires the failure signal it has never had.
- [ ] `memgrep validate` + `memgrep lint` clean on the page.

## Notes and lessons learned

The correction to the count was made with `add-lesson --supersedes`, so the stale
"39" is preserved verbatim as a dated record rather than overwritten. A corrected
inventory that silently drops its own history teaches nobody why it was wrong.
