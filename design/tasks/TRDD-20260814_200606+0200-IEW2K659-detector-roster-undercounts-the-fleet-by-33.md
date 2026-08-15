---
trdd-id: IEW2K659
title: The documented detector roster names 39 of 72 detectors — a silently rotting inventory
column: complete
created: 2026-08-14T20:06:06+0200
updated: 2026-08-16T00:22:00+0200
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

## ⏵ DONE 2026-08-16 — reconciled AND defended by a test

Re-measured before acting (the card's figures were two days old): **73 registered, 45 documented,
29 missing** — 28 absent outright plus `agent-context-integrity`, which a whole-page grep counted as
documented on the strength of a passing mention while it belonged to no group at all. All 29 are now
in group bullets with a one-line description of what each DETECTS, sourced from each detector's own
docstring rather than from its name.

A **`memory` group** was added (8th): 6 detectors (`memory-maintenance`, `memory-librarian`,
`memgrep-index-health`, `wikimem-syntax`, `memorize-nudge`, `orphaned-memory-maint`) had no honest
home among the 7 and were being forced into "observability". `memory-scope-leak` deliberately stayed
in supply-chain/security — it is a data-leak guard on a PUSHED corpus, not upkeep.

**The card's real diagnosis is what got fixed.** Reconciling again would have decayed again on the
next addition, because the defect was never the numbers — it was that *"an inventory has no test"*.
`tests/test_detector_roster_completeness.py` now parses the REGISTRATION tuples in `dispatch.py`
(registration is the authority — an unregistered file never runs) and fails naming every detector
missing from a group bullet. Two deliberate design points, both measured rather than assumed:

- membership is scoped to the `- *group:*` bullets, NOT the whole page — the whole-page form counted
  a superseded body / lesson / atom as documentation and was optimistic by exactly one;
- a CONTROL test asserts the parser still finds >50 registrations, so a change to the tuple shape
  cannot make the scanner blind and declare the roster perfect at that moment.

The guard's docstring states what it does NOT prove — that any description beside a name is true —
per the USER lesson `a-doc-guard-that-asserts-a-mention-cannot-see-a-stale-claim`, so its green
cannot be over-read.

Stale recall surfaces were fixed too, since they are what ranking actually reads: the page
`description:` and the atom `desc:`/keywords still said "39". The wrong count survives as dated
lessons `[^2]`/`[^3]` — corrected, never deleted.

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

- [x] Every detector registered in `dispatch.py` appears in the grouped roster.
      All 73, enforced by `tests/test_detector_roster_completeness.py`.
- [x] The count is DERIVED and stated with its measurement method, so the next
      reader can re-check it in one command rather than trusting the number.
      The page now says "73 REGISTERED in `dispatch.py`" and states that the count is of
      REGISTRATION tuples, not files, because a `.py` nothing registers never runs.
- [x] `system-daemon-runaway` (TRDD-HK7IZ21Z) is in the observability group.
- [x] Something makes the next drift VISIBLE. A prose count that only a human can
      falsify will rot again — the whole point of this card. Prefer a check that
      compares the rostered names against `dispatch.py`'s registrations and reports
      the difference, so the inventory acquires the failure signal it has never had.
      Done exactly that way, plus a CONTROL test so a changed tuple shape cannot blind
      the parser into declaring the roster perfect.
- [x] `memgrep validate` + `memgrep lint` clean on the page.

## Notes and lessons learned

The correction to the count was made with `add-lesson --supersedes`, so the stale
"39" is preserved verbatim as a dated record rather than overwritten. A corrected
inventory that silently drops its own history teaches nobody why it was wrong.
