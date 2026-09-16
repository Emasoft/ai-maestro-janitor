---
trdd-id: 2112XCKO
title: Orphaned memory-maint-pending detector — a silently dropped memory pass must alarm
column: complete
created: 2026-08-08T08:59:51+0200
updated: 2026-08-13T03:58:00+0200
current-owner: janitor-main-session
task-type: feature
approval-tier: 0
relevant-rules: []
npt: []
eht: []
implementation-commits: [9e75a7d9, 169d967d, 74420875]
external-refs: [janitor#238, janitor#232]
---

# Orphaned memory-maint-pending detector — a silently dropped memory pass must alarm

## Why

The memory-maintenance scheduler writes `.janitor/state/memory-maint-pending.json` and the
heartbeat emits a `[janitor-memory-<chore>]` marker; a background subconscious agent is then
supposed to consume the pending file and run the pass. When the spawn fails (plugin partially
installed, agent name unresolvable, session died between marker and spawn), the pending file
sits unconsumed and the pass is SILENTLY dropped — nothing re-fires it and nothing reports the
drop. Measured: the AMOA peer session observed 3 consecutive silent drops (2026-08-08). This is
the same failure shape as the orphaned resume flag (#125): a wake-up chain whose last link broke
with no detector watching the evidence it leaves on disk.

## What

A heartbeat detector (`scripts/detectors/orphaned-memory-maint.py`, pattern-copied from
`scripts/detectors/orphaned-resume-flag.py` / `scripts/lib/orphaned_resume.py`):

- A pending `memory-maint-pending.json` older than N× the memory-maintenance cadence
  (`memory_settings.interval_s_for` of the named intervention; default factor 3, mirroring
  `orphaned_resume.stale_window`) is a FINDING — the pass was scheduled and never ran.
- Pure decision layer in `scripts/lib/` (age + cadence in, verdict out), detector shell around
  it, tests for both, mirroring the orphaned-resume split.
- Finding routes through `findings_ledger.record` (HIGH, code like `MEMPASS-ORPHANED`) so it
  surfaces at SessionStart and in `/janitor-findings` — never another silent channel.
- Clearing: the flag being consumed (file gone) clears it; a stale file may also be re-armed by
  re-stamping the marker rather than merely alarming, if that proves safe — decide during
  implementation, but alarm-first is the MVP.

## Acceptance

- [x] Pure lib function with tests: `(pending_age_s, cadence_s, factor) -> orphaned?` —
      `omm.is_orphaned` + `pending_age_s` + `factor_for_scope`, 3 unit tests.
- [x] Detector emits one deduped drift line + ledger entry when orphaned; silent otherwise —
      `test_orphaned_local_pending_alarms`, `test_no_pending_file_is_silent`,
      `test_fresh_pending_is_silent`, `test_superseded_elsewhere_does_not_alarm`.
- [x] A consumed (absent) pending file emits nothing and clears any prior dedupe state —
      `test_repeated_orphan_fires_write_the_ledger_once_then_healing_clears_dedupe`.
- [x] Malformed/unreadable pending JSON is itself a finding —
      `test_read_pending_malformed_json_is_a_finding`,
      `test_read_pending_missing_required_field_is_malformed`,
      `test_malformed_pending_alarms_once_and_recovers`.
- [x] Test that 3 consecutive drops (the AMOA case) produce a finding after the first window —
      **this was the one box no test actually asserted**; added at 74420875 as
      `test_three_consecutive_dropped_passes_alarm_once_not_never`, falsified by forcing
      `orphaned = False`.

## ⏵ STATE — 2026-08-13: complete. Was DONE-BUT-UNCLOSED for 5 days; closed after verification.

Shipped at **9e75a7d9** (2026-08-12), mode-fixed at **169d967d**, acceptance completed at
**74420875**. The card sat at `column: todo` the whole time with `updated: 2026-08-08` and no
`implementation-commits`, i.e. the board claimed unstarted work that was in fact running in
production — the failure mode `the-kanban-is-a-pipeline-that-must-drain` calls worse than an
unstarted card, because it is invisible from the only view anyone consults.

**Verified before closing, not assumed** (a green test file is not evidence the feature is
reachable):
- **Dispatched**: `dispatch.py:326` — `("orphaned-memory-maint", 300, …)`. A detector that
  exists but is never dispatched does nothing, and the file's existence cannot show that.
- **Boxes 1–4** map onto 21 existing tests, listed above.
- **Box 5 did NOT hold.** The nearest test looks like it covers the AMOA case but its own
  docstring scopes it to the CONSUMED-file criterion, and it heals partway through — which is
  precisely what three consecutive drops never do. Ticking it on the name match would have
  closed the card on an unasserted claim.

**Design note worth keeping:** three consecutive drops emit ONCE, because the dedupe key is
`(intervention, scope)` and repeated drops are one standing fact. Both failure directions are
pinned — silence (the original bug) and one-line-per-drop (which trains the reader to filter
the detector out).

## LOCAL scope is the load-bearing case (janitor#238, orchestrator peer)

The "a dropped pass is not lost — another session's heartbeat picks it up" reasoning holds
ONLY for the shared USER root. A LOCAL root belongs to one project: if that project's only
session has the broken registry (#232's partial-install shape — skills present, ZERO
`ai-maestro-janitor:*` agents enumerable while the cache dir has all 3), the pass is not
deferred but STRANDED until the project gets a healthy session. #238 measured 4 consecutive
drops in one session, 3 of them LOCAL, each with fresh valid pending state and a failed spawn.
Therefore: the staleness bound SHOULD be tighter for LOCAL-scope pending files than USER-scope
ones, and the finding text should name the stranding ("no other session can recover this
scope") so the reader restarts the session rather than waiting.

Also confirmed by #238's discriminating test: bare AND qualified agent names both fail in an
affected session, both enumerating zero janitor agents — availability, not naming — matching
the heartbeat-protocol rule's #232 guidance verbatim.

## Notes

Sibling precedent: `orphaned-resume-flag.py` (#125) — same chain shape, same stale-window
derivation from the armed cadence, same fail-open reads.
