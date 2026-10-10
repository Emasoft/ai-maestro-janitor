---
trdd-id: LSGY6PKA
title: One rate limit records a usage cap for both windows with no attribution
column: blocked
status: tasked
created: 2026-10-05T22:11:15+0200
updated: 2026-10-10T16:30:24+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:15+0200
blocked-by: [AWIWXJIG]
pre-block-column: todo
---

# One rate limit records a usage cap for both windows with no attribution

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

observe_wall writes the freshest reading of the 5h and of the 7d window from a single 429. Cap learning is off since TRDD-YVC3F06V; this is the defect to remove before it is switched on again.

## Approval log

- 2026-10-05T22:11:15+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Findings

2026-10-10 16:30. READ by the main session, no code. Confirmed in scripts/oauth_rotator/burn_gate.py: observe_wall loops over both windows and record_cap_sample appends each ring's freshest reading, so one event writes a cap sample for 5h and for 7d with nothing saying which window was hit. It cannot act today: observe_wall has no caller and cmd_auto discards learned_caps every tick. The cure is already a stated requirement of TRDD-AWIWXJIG ('the cap must be attributed to ONE window'), and this card's own text says it is the defect to remove before cap learning is switched on again. So this card is BLOCKED on TRDD-AWIWXJIG (backburner, open): it is done inside that redesign or not at all. Field case: none possible while the path is dormant.
