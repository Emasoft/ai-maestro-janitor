---
trdd-id: 23QM8H5F
title: memgrep new-mem-atom truncates a long description mid-word instead of refusing or wrapping
column: todo
created: 2026-09-22T21:33:27+0200
updated: 2026-09-24T13:29:28+0200
current-owner: janitor-main-session
created-by: Emasoft
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: Emasoft
approval-datetime: 2026-09-22T21:33:27+0200
---

# memgrep new-mem-atom truncates a long description mid-word instead of refusing or wrapping

Observed 2026-09-22 on .claude/project/memory/macos-keychain.md after the memgrep split
chore: `memgrep new-mem-atom` truncated a long `description:` mid-word instead of refusing
or wrapping it at the cap. Four descriptions were cut mid-word (e.g. "hit the iden" instead
of the full phrase); fixed by hand in commit ebe664f9.

The fix belongs in the memgrep crate (scripts/memgrep), not in the memory pages themselves:
`new-mem-atom` (and any other verb writing `description:`) must either reject a description
over the 200-char cap with an actionable error, or wrap/truncate at a word boundary --
never cut mid-word silently. Silent mid-word truncation is unfindable at write time and
corrupts the recall ranking surface (description is the only field memgrep ranks on).

## Approval log

- 2026-09-22T21:33:27+0200 — MANDATE issued by Emasoft (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-24T13:29:28+0200 — column → todo by janitor-main-session. recurred 2026-09-24 via the janitor-memory-split chore in AgentlensPro; validate and lint passed the truncated descs

## Recurrence 2026-09-24

Reported by the AgentlensPro Claude session (cross-session message, 2026-09-24 ~12:48): on janitor 3.5.7 a [janitor-memory-split] heartbeat marker dispatched janitor-memory-subconscious-agent on the AgentlensPro PROJECT memory; it decomposed 5 over-budget atoms into 10 new atoms across 4 pages and reported "no content lost, memgrep validate/lint pass", but 3 of the 10 new atoms had a desc cut mid-word: ATOM-BWCK-2PMH ended "…so exitNow ", ATOM-AMK3-HO2P ended "…so it c", ATOM-W2SV-B308 ended "…the next atte". memgrep validate and lint both passed on the truncated pages, so no gate caught it.
Reporter's hypothesis, not verified: a fixed character cap applied to the generated desc (all three cut at a similar length) with no word or sentence boundary check. Suggested guard: refuse or flag a desc that ends mid-word, plus a memgrep lint rule for it. Which write verb the split chore used is not yet identified (this card's title names new-mem-atom). Evidence: in the AgentlensPro repo, reports/janitor-memory-subconscious-agent/20260924_122845+0200-split-project.md; the descs were repaired there by hand. Moved to todo: it recurred through a second path and no gate catches it.
