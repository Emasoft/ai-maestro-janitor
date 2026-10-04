---
trdd-id: BHIS99XE
title: C20 — registry integration
column: ai_review
status: tasked
created: 2026-10-01T19:45:12+0200
updated: 2026-10-04T14:53:52+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:12+0200
blocked-by: []
pre-block-column: 
blocker-probe: [trddgrep, why, BHIS99XE]
blocker-holds-if: not-match:READY
implementation-commits: [ef58378a]
---

# C20 — registry integration

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C20, wave W2.

Writes (exclusive): src/memory.rs
Task: Registry integration: push-site severity comes from rule(); the floors and grandfathered lists are derived from gate_floor; test every_emitted_code_is_registered; fix the F2/F16 comments
Verify: Rust gate passes; lint --no-fix output on the PROJECT memory is byte-identical before vs after, except D1's two codes
Depends on: C10
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:12+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:08+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 2UAEQQ4A per DSN035UN wave order
- 2026-10-01 — FACT from C01 (supersedes plan F1 "37 literals"): memory.rs has 34 `code: "` literals; six memgrep codes are emitted without one (atom-no-ocd, atom-no-lmd, atom-bad-ocd, atom-bad-lmd, publish-globally-not-symlinked, publish-globally-conflict). every_emitted_code_is_registered must therefore NOT rely on a `code: "` source scan alone: find how those six are constructed (tldr/jgrep) and cover them, e.g. by asserting the registry against the codes produced by linting a fixture corpus that triggers every rule, or by scanning every string literal passed into a Violation.
- 2026-10-01 — STYLE (wave-1 review finding 7): C02 placed the new mod lines after const MD_EXTS in main.rs instead of inside the existing mod block; move them into the block when this card touches main.rs.
- 2026-10-04T13:11:01+0200 — column → todo by main-agent@ai-maestro-janitor. blocker 2UAEQQ4A is complete and archived Cleared blocked-by (--clear-blocker override).

## Result and open items (2026-10-04)

- DONE in ef58378a: every production push site in memory.rs takes its severity from the registry through rule_sev (40 lookups); write_gate_floors and the grandfathered set are derived from the registry gate_floor field and equal the old lists (14 and 8); new test every_emitted_code_is_registered, shown to fail on an unregistered code; F2 and F16 comments fixed.
- VERIFIED by the main agent: clippy clean; 410 plus 1 ignored and 196 tests pass; each push site asks the registry for the same code it emits; old severities equal the registry at every parsed site except D1; no other source file emits lint codes. From the worker: lint output on LOCAL, PROJECT and USER memory byte-identical before and after except atom-no-ocd and atom-no-lmd (WARN to INFO), same exit codes.
- OPEN: the grandfathered set excludes atom-dup-id and link-downward-cross-scope by name because the registry has no per-page or cross-page field; a new cross-page ERROR code would join the set silently. Add the field to issue-codes.toml and drop the exclusion.
- OPEN: test every_error_code_lint_page_text_emits_is_classified no longer checks anything independent, since both lists derive from one table; rewrite it against an independent source.
- OPEN: rule_sev panics on an unregistered name, so such a code stops a lint run; the new test is the only guard and it scans memory.rs only. C21 and C24 add codes; if any is emitted from another file the scan must be widened.
- OPEN: rules_gen.rs still carries its dead-code allow marked until C20; the generator must drop it.
- OPEN: the STYLE note about mod lines in main.rs was not done (outside the write set).
- OPEN: not established whether any memory chore or precheck counts WARN findings in general and so loses about 80 candidates after the D1 downgrade.
- DEVIATION: the plan prerequisites worktree per card and owner decision on tool exceptions were skipped; one worker wrote one file, and the skip-and-report rule was applied.
- OPEN: every_emitted_code_is_registered scans memory.rs up to the first test module only; the production function footnote_block_marker sits after it (between two test modules) and is not scanned. It emits no code today. The scan regex also accepts lowercase-and-hyphen names only; no registry name has a digit today. Widen both before C21 adds codes.
- VERIFIED after the commit, by the main agent: the lookup name equals the emitted code at all 40 sites including the four publish-globally arms and the three cross-page sites; a recursive search of the crate source and tests finds no lint code emitted outside memory.rs. NOT independently verified: that the derived grandfathered set equals the old list (worker table only; the floor set is covered by the pre_write sweep test).
- INCIDENT: the commit was refused twice by a zero-byte .git/index.lock created 14:15:37 by an unknown process, with no git running. It was removed after 34 minutes by scripts/lib/git_utils.clear_stale_index_lock (returned removed). Second lock collision on 2026-10-04; the creator is not identified.
