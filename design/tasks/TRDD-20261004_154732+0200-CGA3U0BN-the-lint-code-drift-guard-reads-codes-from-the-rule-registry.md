---
trdd-id: CGA3U0BN
title: The lint-code drift guard reads codes from the rule registry instead of scraping memory.rs
column: backburner
status: tasked
created: 2026-10-04T15:47:32+0200
updated: 2026-10-04T15:48:05+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-04T15:47:32+0200
parent-trdd: BHIS99XE
---

# The lint-code drift guard reads codes from the rule registry instead of scraping memory.rs

Problem. tests/test_memory_lint_gate_coverage.py extracts the lint codes by regex-scraping scripts/memgrep/src/memory.rs: text inside `violations.push(Violation { … })` blocks, plus (since commit bc2bfb65) `let code = …;` bindings. Commit ef58378a made scripts/memgrep/src/rules_gen.rs (generated from issue-codes.toml) the source of truth for every code, so the scraper now guards a shape, not the code set. It already broke once (bc2bfb65: two live codes reported as removed when their literals moved into a binding), and C21 (TRDD-3HLI7DMK) changes how codes reach a push again.

Known weaknesses of the scraper (adversarial reviews, 2026-10-04): the push-block pattern runs on past a match arm's bare `})` and takes in whatever sits between two pushes; a code bound under another variable name, passed to a helper, or emitted outside memory.rs is invisible; the binding scan covers the whole file including the Rust test module; the Rust side has its own stricter emitted-code scan (84cec0d8) and the two can disagree.

Change. Read the code names from the registry (`name: "…"` in rules_gen.rs, or issue-codes.toml) and check the classification table against that set.

Consequence that must be decided, not defaulted. The registry has 46 names; the table has 38. The 8 not classified today: blanket-noqa, index-stale-rebuild, lint-over-budget, publish-globally-conflict, publish-globally-missing, publish-globally-not-symlinked, recall-over-budget, unused-noqa. Each needs a conscious row (covering chore, or orphaned with the reason), and the count constant moves 38 -> 46. The file's docstring claim "every memgrep lint CODE" becomes true only then.

Done when. The extractor no longer reads memory.rs; all registry names are classified; a code added to or removed from the registry without a table edit fails the test (prove with one mutation each way); the scraper regexes and their comments are deleted.

Not before. 3.7.1 is published and C21 has landed, so the registry shape is final.

## Approval log

- 2026-10-04T15:47:32+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Open defects carried here

The comment above _PUSH_BLOCK_RE (commit bc2bfb65) says the run-on 'only adds text that is itself a later push block'. That is false - it takes in everything between two pushes, including the next arm's let binding. Comment only, the test behaves correctly. Not fixed on 2026-10-04 because fastedit cannot target module-level comment lines (refusals - Symbol '_PUSH_BLOCK_RE' not found - Whole-file merge rejected, 364 lines exceeds 150-line safety limit). This card deletes that comment.
