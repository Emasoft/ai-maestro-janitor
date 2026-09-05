---
trdd-id: LDSCQ0NU
title: janitor-memory-split marker fires against an empty claim pool costing a full agent spawn to abstain
column: testing
created: 2026-09-05T16:05:02+0200
updated: 2026-09-05T18:30:30+0200
current-owner: main-session
task-type: bugfix
priority: low
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [janitor-heartbeat, memory-dispatch, cost]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: [9681eb7c]
external-refs: [janitor#300]
---

# janitor-memory-split marker fires against an empty claim pool costing a full agent spawn to abstain

## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-09-05T18:11:33+0200

Directory-mismatch hypothesis (coordinator, round 3) CHECKED AND REJECTED, by
reading, not reasoning:

- `state.state_dir()` (writer: `memory-maintenance.py::_write_pending`, and
  claimer: `memory_dispatch_claim.py` — all 8 `janitor-memory-*` SKILL.md
  files invoke it with NO `--state-dir` override, e.g.
  `skills/janitor-memory-split/SKILL.md:73`) resolve via the IDENTICAL
  function/env var (`CLAUDE_PROJECT_DIR`) — same code path, same directory.
  Measured on this host: both resolve to
  `/Users/emanuelesabetta/Code/AI-MAESTRO-JANITOR/ai-maestro-janitor/.janitor/state`,
  which right now holds 14 real `memory-maint-pending-<id>.json` files.
- `global_state.global_state_dir()` — what the issue #300 reporter checked
  ("a read-only look at global-state/") — is a DIFFERENT, DELIBERATELY
  different directory
  (`~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state`),
  used for cadence stamps / the dispatch flock / the in-flight TTL record —
  NEVER for pending-dispatch records. It holds zero
  `memory-maint-pending*` files by design; that is not evidence of an
  empty pool.
- Conclusion: no directory-mismatch bug exists in the code. The reporter's
  manual check looked in the wrong directory for the artifact it was
  looking for. The write-time gate (`is_claimable`) and relay-time gate
  (`_suppress_stale_memory_markers`) already landed are the complete fix
  for the ACTUAL race (a peer session's agent claiming the dispatch in the
  spawn-latency window) — no further code change follows from this round.

## Why

`[janitor-memory-split]` fired on two consecutive heartbeats against an
empty claim pool. Fire 1 (~18:58 local) dispatched
`janitor-memory-subconscious-agent` per the heartbeat protocol; the claim
step returned exit 2 ("no claimable memory-maintenance dispatch") and the
agent abstained correctly, mutating nothing — but the spawn cost 326664
subagent tokens, 4 tool calls, 27s. Fire 2 (~19:04 local) was the same bare
marker against the same empty pool (a read-only check found no unclaimed
dispatch record).

The scheduler's content precheck (which gates the marker) and the claim pool
(which gates the agent's only legal action) are two independent conditions.
When the precheck says "content-due" but the claim pool is empty (e.g. a
peer session claimed the dispatch first), every session receiving the marker
pays a full agent spawn just to learn it lost the race — the marker carries
no way to distinguish "nothing due" from "someone else already took it".

Secondary, lower-confidence observation: fire 1's agent reported its chore
as `consolidate` while the marker said `[janitor-memory-split]` — a possible
chore-name default when the claim returns nothing rather than a
mismatch-with-real-work case (janitor#273/#275/#280 already fixed the known
mismatch class).

## What

Either direction removes the cost (issue reporter expressed no preference):
- Gate the marker itself on the claim pool, not only on the content
  precheck — do not emit `[janitor-memory-split]` when nothing is claimable.
- Make the abstain cheap: let the dispatcher stub attempt the claim itself
  and emit nothing on exit 2, so the marker is only ever emitted to a
  session that actually has claimable work. Keeps the "CLAIM, never read a
  shared file" invariant intact since the stub claims on the agent's behalf
  within the same fire.

## Acceptance criteria

- [x] A heartbeat fire against an empty claim pool no longer spawns a full
      `janitor-memory-subconscious-agent` — TWO gates, at the two points a
      marker can go stale:
      1. WRITE-TIME (same process): `scripts/detectors/memory-maintenance.py::_run`
         calls `memory_dispatch_claim.is_claimable(state_dir, dispatch_id,
         intervention)` right after writing the per-dispatch record and
         BEFORE printing the marker / recording the in-flight stamp. Cheap,
         correct, but by construction can only catch a write that itself
         failed — traced (2026-09-05) and confirmed there is NO existing
         path in `_run` that prints the marker without a fresh write in the
         same call (the in-flight-deferred branch returns before printing;
         nothing reads the legacy `memory-maint-pending.json` slot or
         replays the cursor into a print).
      2. RELAY-TIME (the actual fix for janitor#300's fire 2 / the
         peer-claimed-first race): `scripts/dispatch.py::
         _suppress_stale_memory_markers`, called from `_run_detector`
         immediately after the `memory-maintenance` subprocess exits and
         BEFORE its stdout is written to the heartbeat's own stdout — the
         last point machine code can still catch a record a peer session's
         agent claimed in the minutes between the scheduler's write and
         this relay. Reuses `memory_dispatch_claim.candidates()` +
         `payload_matches_chore` (renamed from `_payload_matches_chore` —
         now a public, cross-module-shared predicate, not re-implemented).
      Proven at the predicate level by `tests/test_memory_dispatch_claim.py::
      test_is_claimable_false_for_a_missing_dispatch_id` /
      `test_is_claimable_false_on_chore_mismatch`, and at the relay level by
      `tests/test_dispatch_defang.py::
      test_marker_suppressed_when_claim_pool_is_empty` (writes a pending
      record, claims it with the REAL `memory_dispatch_claim.claim_one`,
      then asserts the relay suppresses the now-stale marker).
- [x] A heartbeat fire against a non-empty claim pool is unaffected — proven
      by all pre-existing marker-emission tests in `tests/test_memory_maintenance.py`
      still passing unchanged (e.g. `test_due_emits_the_right_bare_marker`,
      `test_emit_writes_pending_sidecar`), the write-time
      `test_emitted_marker_dispatch_is_claimable_by_the_claim_script`, and
      the relay-time `tests/test_dispatch_defang.py::
      test_marker_survives_when_the_dispatch_is_still_pending` (a genuinely
      unclaimed matching record → the marker leaves the relay byte-for-byte
      unchanged).
- [ ] Chore-name-mismatch-with-a-claimable-dispatch is explicitly OUT OF
      SCOPE for this TRDD (per the criterion's own text) — left unticked on
      purpose; no code here attempts it. `is_claimable`/`claim_one`/the
      relay gate now share one `payload_matches_chore` predicate (was
      duplicated inline in `claim_one`) so all three can never silently
      diverge on what "matches" means, which is the only change this TRDD
      makes in that direction.

## Deployment note (read before assuming this reached the running heartbeat)

The fix lives in the REPO SOURCE (`scripts/detectors/memory-maintenance.py`,
`scripts/memory_dispatch_claim.py`) — the emitter. The INSTALLED
`~/.claude/plugins/data/…/dispatcher-stub.py` only `execv`s into the newest
**cached** plugin version; this change reaches a running heartbeat on any
host only after that host's plugin cache is updated to a release containing
it (see CLAUDE.md's `claude plugin update … @…marketplace` step). Testing
here proves the code, not that "the marker no longer fires on this host".

## Notes and lessons learned
