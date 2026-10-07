---
trdd-id: GTP15HRC
title: Lint misses a repeated phrase in a single-quoted description
column: testing
status: tasked
created: 2026-10-05T01:53:41+0200
updated: 2026-10-07T07:01:32+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T01:53:41+0200
implementation-commits: [b6d5db58]
---

# Lint misses a repeated phrase in a single-quoted description

Found 2026-10-05 in the review of C17 (archived TRDD-KSCAFSLD). For description: 'a b / c d / a b' lint reports no page-description-duplicated-phrases finding, although a phrase repeats. Cause, read in source: lint and the dedup_phrases fixer share page_description_phrases (scripts/memgrep/src/memory.rs, near line 5599), which trims only double quotes, so the first phrase keeps its leading quote and never equals the repeat. The fixer correctly declines, because it acts only where lint reports. Measured in the test single_quoted_value_is_fixed_correctly_or_refused (scripts/memgrep/src/fixers/dedup_phrases.rs), which asserts lint is silent and the fixer returns None; that test name is now misleading and should be renamed when this is fixed. Fix: make page_description_phrases read a single-quoted YAML scalar (a doubled quote is the escape), then reverse that test. Verify: lint reports the code on the single-quoted page, the fixer output keeps the single quotes, and the oracle passes.

## Approval log

- 2026-10-05T01:53:41+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T07:01:32+0200 — column → testing by main-agent@ai-maestro-janitor. batch B1-B3 merged on main, gated

## STATE

2026-10-07 merged on main (b6d5db58): lint unquotes a single-quoted YAML description (doubled quote collapsed to one) before splitting, so a repeated first phrase is caught; the dedup fixer keeps single quotes. The old test pinned the miss and was reversed. Open before release: the fixer may emit an unbalanced quote for a value single-quoted only at the start (it should refuse); and existing memory pages that were clean may now be flagged, uncounted. Not in a release yet.
