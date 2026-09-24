---
trdd-id: DZ1KOGAC
title: Control inputs fill the owner tier of the injected Jev copy
column: testing
created: 2026-09-24T11:21:11+0200
updated: 2026-09-24T13:39:06+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T11:21:11+0200
implementation-commits: [bf523e8d, c597a709, 12351362]
---

# Control inputs fill the owner tier of the injected Jev copy

Same run (E2). The owner tier of the injected copy is filled with control inputs: `resume`, `RESUME`, `/compact` twice, `/goal` and `/eli5` command wrappers. They displace the owner's real instructions. Whether they were decision-passing is not yet measured. Direction (advisor, 2026-09-24): a content predicate, not authorship; see Review corrections below. /goal and /eli5 with arguments stay as owner items. Acceptance: on the three transcripts no injected owner item is a bare control word or an argument-less slash command; a test fails without the fix. Release blocker for TRDD-RAEGS1D5.

## Approval log

- 2026-09-24T11:21:11+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-24T12:12:35+0200 — column → testing by janitor-main-session. control-word demotion landed in bf523e8d and c597a709 with failing-first tests; re-measured with the next real-transcript run

## Review corrections 2026-09-24

Advisor: the measured items are owner-typed (origin.kind human), so the rule is content-based, not authorship-based: one predicate is_control_input in transcript_roles (a single token such as resume or continue, or a bare automation slash command) makes extract_items classify the record as kind event (still scored, still pointed at, never in the owner tier, the guaranteed newest slot or the digest), and the recent-turns tail drops it. /goal and /eli5 with arguments, and "yes, post it", are the owner's own words and stay.
Accepted trade: the recent-turns tail no longer shows a bare "resume" or "continue" line, so a resumed session cannot see that the owner's last input was a bare control word.
Re-checked 2026-09-24 against effef26c and git log --grep=DZ1KOGAC: effef26c applied this card's pending bookkeeping (implementation-commits [bf523e8d, c597a709], column testing, the accepted loss of the bare resume line). The previous session's code follow-up also landed: c597a709 strips a trailing '.' or '!' before the control-word match (not '?': 'resume?' stays the owner's message) and pins the newest-owner fallback. Missing until now: 12351362 (an empty-args wrapper of a content-free command such as /compact or /clear is a control input), tagged DZ1KOGAC, added to implementation-commits. The review of 12351362 said its commit message's claim, that decision-bearing commands such as /janitor-disarm stay owner items, is probably moot because classify_record already demotes wrapped janitor-* commands before is_control_input runs (inferred from the advisor's trace, not verified).
