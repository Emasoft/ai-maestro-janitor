---
trdd-id: AWIWXJIG
title: Learn a real usage cap from session rate-limit evidence with one-window attribution and a lifetime bound
column: backburner
status: tasked
created: 2026-10-05T16:31:25+0200
updated: 2026-10-05T16:43:11+0200
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
