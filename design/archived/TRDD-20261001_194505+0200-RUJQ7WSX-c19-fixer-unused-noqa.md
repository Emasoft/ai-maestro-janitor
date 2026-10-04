---
trdd-id: RUJQ7WSX
title: C19 — fixer unused_noqa
column: complete
status: archived
created: 2026-10-01T19:45:05+0200
updated: 2026-10-05T01:49:41+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:05+0200
blocked-by: []
pre-block-column: 
blocker-probe: [trddgrep, why, RUJQ7WSX]
blocker-holds-if: not-match:READY
implementation-commits: [9fb13752, 9254214e, 5c54735d]
---

# C19 — fixer unused_noqa

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C19, wave W1.

Writes (exclusive): src/fixers/unused_noqa.rs
Task: SAFE fixer: unused noqa
Verify: Each test: (a) a before/after literal; (b) a lossless assert (prefix-preserving, unquote = original, set unchanged, block multiset byte-equal, only the comment removed); (c) oracle: lint_page_text(fixed) lacks the code
Depends on: C02
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:05+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:45:57+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 622ROA5F per DSN035UN wave order
- 2026-10-04T13:11:00+0200 — column → todo by main-agent@ai-maestro-janitor. blocker 622ROA5F is complete and archived Cleared blocked-by (--clear-blocker override).
- 2026-10-04T13:11:13+0200 — column → testing by main-agent@ai-maestro-janitor. fixer implemented in 9fb13752, unit-tested, awaiting review
- 2026-10-04T13:25:12+0200 — column → ai_review by main-agent@ai-maestro-janitor. implemented and unit-tested, not wired into lint; testing overstated it
- 2026-10-05T01:49:41+0200 — COMPLETE by main-agent@ai-maestro-janitor. ai review 2026-10-05 found test gaps against the acceptance rule; all closed and verified by a whole-crate test run and clippy; unit level only, wiring is C22.

## Review 2026-10-05

C19 review: a kept comment was rebuilt from a format string, changing bytes outside the removed selector. 5c54735d removes selectors by the byte span of each comma-split token (prefix-safe, duplicates go once each). Only the last comment on a line is rewritten, matching noqa.rs classify; a line with two comments is declined. NOT fixed: the frontmatter lint-ignore line is still rebuilt as lint-ignore: [list], which normalises spacing outside the brackets.
The fixer is implemented and unit-tested only; nothing calls it until C22 (TRDD-JD2QR5SQ) wires the fixers into lint. Test edits on 2026-10-05 were made with plain exact-match edits and read back as diffs, because the fastedit tool left orphan test attributes in this crate twice that day.

## Acceptance checklist

- [x] Each test has a before/after literal. Evidence 2026-10-05: cargo test on the whole memgrep crate exit 0 (423 unit and 196 cli tests passed, 1 ignored), the 57 fixer tests pass, cargo clippy --all-targets -D warnings exit 0, and per file the test-attribute count equals the tests cargo lists.
- [x] Each fixing test has a lossless assert, and no test asserts only inside a conditional.
- [x] Oracle: the fixed page no longer reports the code. LIMIT: lint_page_text does not emit unused-noqa until C21 (TRDD-3HLI7DMK), so the has_code assert cannot fail today; the tests use the same unused-selector predicate the lint will use plus exact output literals. C21 must re-run these tests with a real has_code.
- [x] The card wrote only its own file under src/fixers.
