---
trdd-id: 23QM8H5F
title: memgrep new-mem-atom truncates a long description mid-word instead of refusing or wrapping
column: testing
created: 2026-09-22T21:33:27+0200
updated: 2026-09-25T16:18:40+0200
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
status: tasked
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
- 2026-09-25T16:18:40+0200 — column → testing by main-agent@ai-maestro-janitor. Rust guard + test landed; memgrep suite 436 green

## Recurrence 2026-09-24

Reported by the AgentlensPro Claude session (cross-session message, 2026-09-24 ~12:48): on janitor 3.5.7 a [janitor-memory-split] heartbeat marker dispatched janitor-memory-subconscious-agent on the AgentlensPro PROJECT memory; it decomposed 5 over-budget atoms into 10 new atoms across 4 pages and reported "no content lost, memgrep validate/lint pass", but 3 of the 10 new atoms had a desc cut mid-word: ATOM-BWCK-2PMH ended "…so exitNow ", ATOM-AMK3-HO2P ended "…so it c", ATOM-W2SV-B308 ended "…the next atte". memgrep validate and lint both passed on the truncated pages, so no gate caught it.
Reporter's hypothesis, not verified: a fixed character cap applied to the generated desc (all three cut at a similar length) with no word or sentence boundary check. Suggested guard: refuse or flag a desc that ends mid-word, plus a memgrep lint rule for it. Which write verb the split chore used is not yet identified (this card's title names new-mem-atom). Evidence: in the AgentlensPro repo, reports/janitor-memory-subconscious-agent/20260924_122845+0200-split-project.md; the descs were repaired there by hand. Moved to todo: it recurred through a second path and no gate catches it.

## STATE

2026-09-25 15:45 — implemented (Rust): check_desc gains the ATOM_DESC_MAX_CHARS=200 maximum (shared constant with sanitize_quoted_value's cap), so every write verb (new-mem-atom, update-mem-atom, split's two call sites) REFUSES an over-cap desc with a message naming the fix, instead of the marker builder silently truncating mid-word. Page description: stays uncapped. Pinned by desc_over_the_atom_cap_is_refused_not_truncated_mid_word (refusal text, ==cap ok, 201 refused); full memgrep suite 436 passed. 3 pre-existing over-cap descs exist in USER scope (verify-cross-repo-cited-sha x2, debugging-methodology...full-3-atom) — they are legal as-written; the guard fires only when a write verb next touches them. Column -> testing.
