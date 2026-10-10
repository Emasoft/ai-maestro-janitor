---
trdd-id: SUUDAXRT
title: The card tool cannot parse a cross-repo blocker or unset a field
column: human_review
status: tasked
created: 2026-10-07T09:36:04+0200
updated: 2026-10-10T23:22:10+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T09:36:04+0200
---

# The card tool cannot parse a cross-repo blocker or unset a field

trddgrep reads a blocked-by of the form owner/repo#N as an unknown card and has no verb to remove a field (seen on 2AVXCT2L and CGA3U0BN). The tool belongs to the ai-maestro repo: file the issue there on the Emasoft fork. Not fixed here.

## Approval log

- 2026-10-07T09:36:04+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T23:22:10+0200 — column → human_review. both defects reproduced on a scratch corpus; the tool belongs to another repository, draft issue on the card

## STATE

2026-10-10 23:45 REPRODUCED on a scratch corpus outside the repository (one new card; TRDD-S6GX1DHN wave 23 card 1), no change here. (1) CROSS-REPO BLOCKER, half paid already. A blocker written as owner/repo#N still gives the error GRAPH-UNKNOWN-BLOCKER. Written as gh:owner/repo#N it is accepted and the lint gives only the warning GRAPH-EXTERNAL-BLOCKER; TRDD-1T9034NC on this board uses that form. So a legal spelling exists and what is left is that the bare form fails with a message that does not name the gh: form (the message text was not read in full). (2) NO WAY TO REMOVE A FIELD, confirmed. set with no value is refused. set with an empty value leaves the field present and empty. unset is read as a search pattern. And set with the value --unset writes the literal text --unset into the field, which is a defect of its own (a value shaped like a flag is stored). (3) An archived card refuses every set, including the successor field (tried on a copy of TRDD-YXY992BN), so the open point of TRDD-BIQELG5J is answered and its 5 remaining lint errors are not fixable from this board. Existing issues in the ai-maestro repository, by title only: none found for removing a field under two searches; 177 covers a decision-only blocker and 170 archived repairs. DRAFT ISSUE for Emasoft/ai-maestro, NOT posted. Title, trddgrep has no verb to remove a frontmatter field, and set stores a flag-shaped value. Body, from the janitor project board, 2026-10-10. To clear review-after or blocked-by one can only write an empty value, which leaves the key. set ID blocked-by --unset stores the text --unset. Asked, an unset verb (or set --unset) that deletes the line, and a refusal of values that begin with two dashes. Also, the GRAPH-UNKNOWN-BLOCKER message for owner/repo#N could name the gh: form. OWNER ITEM, post or drop this draft.
