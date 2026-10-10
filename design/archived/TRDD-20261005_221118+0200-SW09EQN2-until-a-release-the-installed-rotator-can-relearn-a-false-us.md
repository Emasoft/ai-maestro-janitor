---
trdd-id: SW09EQN2
title: Until a release the installed rotator can relearn a false usage cap
column: complete
status: archived
created: 2026-10-05T22:11:18+0200
updated: 2026-10-10T16:29:10+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:18+0200
---

# Until a release the installed rotator can relearn a false usage cap

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

The fix of TRDD-YVC3F06V is unpublished. On one host the caps were cleared by hand; the next throttle episode can write them again.

## Approval log

- 2026-10-05T22:11:18+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T16:29:10+0200 — COMPLETE by main-agent@ai-maestro-janitor. archived → complete.

## Findings

2026-10-10 16:29. ALREADY PAID, checked by the main session, no code. The fix of TRDD-YVC3F06V (95bbddeb) is in release tags from v3.7.1 on. The installed plugin (3.8.11, the plugin cache copy of scripts/oauth_rotator/rotator.py) discards learned_caps on every tick (1 occurrence of the pop) and has no call of observe_wall (0 occurrences). The live rotator state file holds no learned_caps key today, only usage_samples. NOT CHECKED: whether a rotator run by the ai-maestro server on this host has cap learning of its own; that code is outside this repository.

## Acceptance

- [x] The card says that until a release the installed rotator can relearn a false usage cap. The release exists (v3.7.1 and later) and the installed 3.8.11 neither learns nor keeps caps; the live state holds none on 2026-10-10. This is the card's own case (the installed code and its state), not a proxy. Pinning tests are those of TRDD-YVC3F06V, re-run in every gate today.
