---
trdd-id: GXXKAGY6
title: A retry-wedge signal schedules an immediate rotator tick
column: complete
created: 2026-09-24T11:21:23+0200
updated: 2026-09-28T13:04:13+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T11:21:23+0200
status: archived
---

# A retry-wedge signal schedules an immediate rotator tick

Release 1 of TRDD-RAEGS1D5; item (f) and term D7 on TRDD-4XND73XD. When the 429 retry-wedge is detected, schedule a rotator tick now instead of waiting for the 60 s beat; the tick still respects the usage cache, the cooldown and at most one per MIN_DWELL_S. Acceptance: a test that fails without it.

## Approval log

- 2026-09-24T11:21:23+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
OWNER DECISION 2026-09-27 (verbatim: 'it depends on the context. use heuristic.'): the D7 debounce question is settled as a HEURISTIC, not a fixed rule — the implementation decides per-context whether a retry-wedge signal counts as a debounced 429; record the chosen heuristic in the implementation and let live behavior tune it.
ATTRIBUTION CORRECTION 2026-09-27 (review round on the decision recording): the sentence 'record the chosen heuristic in the implementation and let live behavior tune it' is the RECORDING AGENT'S implementation suggestion, NOT owner words. The owner's decision 6 is exactly: 'it depends on the context. use heuristic.'
- 2026-09-27T17:16:34+0200 — column → testing by user. wedge→immediate-tick landed and verified by main (commit 4e03e63d); 9 new tests + 208 neighbour tests green
- 2026-09-28T13:04:13+0200 — COMPLETE by user. archived → complete.

## Review corrections 2026-09-24

Open decision, to settle before code: how the wedge signal counts against LIVE_429_DEBOUNCE. An immediate tick that still waits out the debounce saves only one beat. Scope stays within term D7 of TRDD-4XND73XD (a trigger only schedules a tick). Counting a wedge as a debounced 429 would amend D7 and needs the ai-maestro Claude's agreement first. Test: a wedge signal starts a tick before the next scheduled 60 s beat, and a second signal inside MIN_DWELL_S starts none.

## Implementation

2026-09-27: landed (commit 4e03e63d) via lean-worker, verified independently by the main agent. Daemon raises rotator-tick-requested.flag on confirmed retry_wedged; main loop consumes clear-before-run; env JANITOR_ROTATOR_WEDGE_TICK=1 crosses to the rotator subprocess; cmd_auto raises the live-429 streak to LIVE_429_DEBOUNCE on a wedge tick (owner heuristic 2026-09-27). D7 guards untouched (usage cache, cooldown, MIN_DWELL_S). 9 new tests + 208 neighbour tests green, ruff clean, pyright clean on touched files.

## Acceptance

- [x] wedge signal schedules a rotator tick before the next 60s beat: tests/test_wedge_rotator_tick.py 9 tests green (run 2026-09-28 exit 0; landed 4e03e63d, main-verified; 9 new + 208 neighbour green)
- [x] the 9 tests pin both required behaviors (tests/test_wedge_rotator_tick.py, run 2026-09-28): a wedge signal starts a tick before the next scheduled 60 s beat, and a second signal inside MIN_DWELL_S starts none; D7 guards (usage cache, cooldown, MIN_DWELL_S) untouched is a diff property of 4e03e63d, verified by source read recorded in Implementation
- [x] owner heuristic applied: wedge tick raises live-429 streak to LIVE_429_DEBOUNCE in cmd_auto (owner decision 2026-09-27, attribution correction recorded): verified by source read in Implementation
