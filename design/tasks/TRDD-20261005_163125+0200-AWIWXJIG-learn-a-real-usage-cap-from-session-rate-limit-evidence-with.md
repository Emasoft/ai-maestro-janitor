---
trdd-id: AWIWXJIG
title: Learn a real usage cap from session rate-limit evidence with one-window attribution and a lifetime bound
column: backburner
status: tasked
created: 2026-10-05T16:31:25+0200
updated: 2026-10-10T14:15:04+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T16:31:25+0200
---

# Learn a real usage cap from session rate-limit evidence with one-window attribution and a lifetime bound

Cap learning must be driven by the stop-failure hook or wedge evidence, regardless of the usage endpoint status. The cap must be attributed to ONE window (5h or 7d), not both, and a learned cap must have a bounded lifetime so a wrong one expires.

Related open problem: the rotator's 429 branch marks rotation stuck on an endpoint throttle when no rotation target exists.

## Approval log

- 2026-10-05T16:31:25+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Preconditions when this lands

(a) The per-tick state.pop("learned_caps", None) in cmd_auto must be removed, or every cap this card learns is erased on the next tick.
(b) The burn_gate cap functions (observe_wall, record_cap_sample, store_caps, the learned-cap arm of live_burn_verdict) are dormant and kept for this card.
(c) Wedge ticks and the stop-failure hook are the candidate evidence sources; the daemon task_oauth_recovery (scripts/daemon.py) is a second launcher of rotator.py auto and must carry the same evidence marker.

## Inherited from TRDD-YVC3F06V (archived 2026-10-10)

2026-10-10 14:35, from the review of 1634f4b8. YVC3F06V is archived and frozen, so what it left open lives here: (1) its limit (a): the stale learned_caps key is erased from disk only on ticks that reach a save (the 200 and 429 paths, and before a switch); it is popped in memory every tick, so it cannot act. (2) its limit (c): alternates are no longer filtered by learned caps in target selection. (3) burn_gate.py's module docstring says 'learned_caps is currently always absent on disk', which is too strong by (1); reword it when this card next edits that file. (4) CORRECTION to YVC3F06V's closing record: its field evidence (a 429 streak x160 on 2026-10-10 followed by no learned_caps key) shows the per-tick pop works; it does NOT show that the 429 branch learns nothing, because the pop would erase a learned cap anyway. Only tests/test_oauth_rotator.py::test_usage_endpoint_429_streak_teaches_no_cap covers that. YVC3F06V should have closed with the words FIELD CASE UNOBSERVED for that half.
