---
trdd-id: 91D2VHW3
title: pre-compact handoff recent turns still include task notifications and command wrappers
column: complete
created: 2026-09-23T20:17:58+0200
updated: 2026-09-27T12:51:20+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-23T20:17:58+0200
derived: true
parent-trdd: RAEGS1D5
status: archived
---

# pre-compact handoff recent turns still include task notifications and command wrappers

Card 2b of the Jev reference gap analysis (2026-09-23). pre-compact-handoff._recent_turns skips isMeta, isSidechain, isCompactSummary and the heartbeat prefix but not task-notification records or command wrappers (<command-message>, <local-command-stdout>). Fix: use scripts/lib/transcript_roles.py (card 1 of TRDD-RAEGS1D5). Separate file, separate commit from card 2a. Test with one fixture line per record class.

## Approval log

- 2026-09-23T20:17:58+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-23T21:10:49+0200 — column → testing. code landed and committed 2026-09-23 with tests; awaiting the real-transcript compaction on the final tree and the release
- 2026-09-27T12:51:20+0200 — COMPLETE by user. owner batch acceptance 2026-09-27 ('complete all TRDDs'); independent lean-worker verdict DONE (batch1).

## Acceptance

- [x] code landed 2026-09-23 with tests per record class (task-notification, local-command-stdout, command-message), passing; shared real-transcript acceptance met
- [x] card evidence current at HEAD; owner batch acceptance 2026-09-27 ("complete all TRDDs")
