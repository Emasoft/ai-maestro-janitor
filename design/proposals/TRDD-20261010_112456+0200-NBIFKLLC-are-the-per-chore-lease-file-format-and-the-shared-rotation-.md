---
trdd-id: NBIFKLLC
title: Are the per-chore lease file format and the shared rotation policy file final on the ai-maestro side
column: proposal
status: proposed
created: 2026-10-10T11:24:56+0200
updated: 2026-10-10T11:24:56+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: user
assignee: user
approved: false
---

# Are the per-chore lease file format and the shared rotation policy file final on the ai-maestro side

Split from TRDD-4XND73XD on 2026-10-10 so that card has a named, open blocker.

THE QUESTION, for the session responsible for the ai-maestro server: (1) is the per-chore ownership lease file format final (term M2 on TRDD-4XND73XD: one lease per chore, lease_until = now + max(150 s, 2.5 x cadence), renewed only by a completed run under one dedicated lease lock); (2) is DATA/oauth-rotator/rotation-policy.json final as the single threshold table (terms M6, R4); (3) where is the committed joint spec (TRDD-4XND73XD names ~/ai-maestro/design/specs/oauth-rotation-and-chore-handover-spec.md as announced, not yet committed).

WHY IT IS WITH THE OWNER: asking is a message to another agent about the rotation protocol; under the board-drain stop list that is the owner's word to give. The owner delegated the protocol decisions to the two sessions on 2026-09-24 ('i leave the decisions to you and the ai-maestro claude'), so a plain go-ahead to send the three questions is all that is needed.

WHAT WAITS ON IT: the janitor-side lease write and renew (item c), the lease half of item (b), refresh_dead_fp (item d) and the shared threshold table (item e) of TRDD-4XND73XD. Building them against a draft risks two daemons disagreeing on who rotates.

## Acceptance

- [ ] The three answers are recorded here, quoted, with the date and who gave them
- [ ] TRDD-4XND73XD's blocked-by is cleared or the card is re-scoped on the answers

## Approval log
