---
trdd-id: XI9UYD4E
title: memgrep update-mem-atom cannot desc-edit a footnote-lesson atom (stdin body mandatory even for empty body spans)
column: testing
status: tasked
created: 2026-09-25T17:39:50+0200
updated: 2026-09-26T05:25:32+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-09-25T17:39:50+0200
---

# memgrep update-mem-atom cannot desc-edit a footnote-lesson atom (stdin body mandatory even for empty body spans)

## Approval log

- 2026-09-25T17:39:50+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-25T21:29:34+0200 — column → testing by main-agent@ai-maestro-janitor. implemented + migration completed; 441 memgrep tests green
- 2026-09-25T23:53:42+0200 — CORRECTION (append-only note on the 21:29 line above): its "migration completed" claim is RETRACTED — the migration silently deleted 3 lesson inline bodies; see the STATE block's CORRECTION 2026-09-25 (T-H97PEEQZ) for the recovery and the fix.

## STATE

2026-09-25 21:40 — implemented: locate_atom_body_matching recognises '[^N]: [id:ATOM-...]' as a lesson marker (span = marker line only; a sibling footnote closes the span); update-mem-atom reads stdin only when the body span is non-empty and preserves the '[^N]: [...]' marker shape on rebuild (footnote_block_marker parses the props). 3 new tests (span, marker parse, CLI end-to-end without stdin); memgrep 441 green. The review's 3-desc migration ran with this verb: all 3 over-cap lesson descs shortened, zero over-cap descs remain corpus-wide. CORRECTION 2026-09-25 (T-H97PEEQZ): the migration's stdin-less desc-only edit SILENTLY DELETED all three lessons' inline bodies — the pre-XI9 verb refused (empty body on stdin), the refusal had been masking the body loss, and the XI9 empty-span rebuild replaced the whole marker line without the inline tail. All three bodies were recovered verbatim from pre-damage transcript reads and restored through memory_txn repair txns; update-mem-atom now preserves the inline body (fix branch fix/update-mem-atom-inline-lesson-body, memgrep commit 00bc8acb, regression test watched to fail on the pre-fix binary). REMAINING GATE: the fix branch is UNMERGED into main — the incident is not closed until fix/update-mem-atom-inline-lesson-body merges (XI9UYD4E) and the owner approves publishing. GATE CLEARED 2026-09-26 05:25: fix/update-mem-atom-inline-lesson-body was ff-merged into main (a9626a8e → 2f5b7e74, no push; publishing remains owner-gated); memgrep suite re-run green on main post-merge (159 lib tests, exit 0).
- DO NOT mark a migration COMPLETED when the verb's output was not diffed against the source, BECAUSE a silent data loss (three lesson bodies deleted, exit 0) reads as success in the command's own one-line output and in a test suite that never asserted body survival — caught 2026-09-25 by T-H97PEEQZ when lint raised lesson-empty-body on all three pages. DO diff the mutated line against its pre-edit form before declaring a data-preserving migration done, and add the survival assertion to the test that exercises the verb.
