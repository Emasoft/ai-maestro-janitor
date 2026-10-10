---
trdd-id: V7QQ8PKO
title: Four cap functions of the burn gate are no longer called by production code
column: complete
status: archived
created: 2026-10-05T22:11:16+0200
updated: 2026-10-10T16:30:23+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:16+0200
---

# Four cap functions of the burn gate are no longer called by production code

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

observe_wall, record_cap_sample, store_caps and the learned-cap arm of live_burn_verdict are reached only by tests since TRDD-YVC3F06V. Decide: keep for TRDD-AWIWXJIG with a note in the code, or delete.

## Approval log

- 2026-10-05T22:11:16+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T16:30:23+0200 — COMPLETE by main-agent@ai-maestro-janitor. archived → complete.

## Decision

2026-10-10 16:30. DECIDED by the main session under the mandate: KEEP, no code. READ today (scripts/oauth_rotator/burn_gate.py lines 119 to 245, and every use under scripts): observe_wall, record_cap_sample and store_caps have no caller outside the module and its tests; the learned-cap arm of live_burn_verdict and effective_switch_at run on an always-empty cap list, because cmd_auto pops learned_caps on every tick; account_caps is still called in target selection (rotator.py 2839) and returns nothing. The note the card asks for is already in the code: the module docstring says cap learning is off and the paths are kept, inert, for TRDD-AWIWXJIG, and observe_wall's own docstring says it has no caller (both from 1634f4b8). WHY KEEP and not delete: TRDD-AWIWXJIG's recorded precondition (b) says these functions are kept for it; they are pure, covered by tests/test_burn_gate.py and green in today's gates; deleting them is a rotator change with a full gate for no change in behaviour, and the redesign would write them again. AGAINST, stated so it is not lost: the project rule is one version of the code and no legacy code; this is dormant code held for a backburner card that may never be pulled, and it carries two known defects (TRDD-LSGY6PKA, TRDD-WJVXIQRL). If TRDD-AWIWXJIG is ever cancelled or redesigned without these functions, they are deleted in that change; that condition is written on AWIWXJIG in this commit.

## Acceptance

- [x] The card says: decide, keep for TRDD-AWIWXJIG with a note in the code, or delete. Decided: keep. The note is in the code (module docstring and observe_wall docstring of scripts/oauth_rotator/burn_gate.py, read 2026-10-10). No code changed, so there is no test to name and no field case.
