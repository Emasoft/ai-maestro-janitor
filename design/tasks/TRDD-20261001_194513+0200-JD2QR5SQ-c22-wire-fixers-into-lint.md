---
trdd-id: JD2QR5SQ
title: C22 — wire fixers into lint
column: dev
status: tasked
created: 2026-10-01T19:45:13+0200
updated: 2026-10-06T20:14:45+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:13+0200
blocked-by: []
pre-block-column: 
blocker-probe: [trddgrep, why, JD2QR5SQ]
blocker-holds-if: not-match:READY
---

# C22 — wire fixers into lint

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C22, wave W2.

Writes (exclusive): src/memory.rs, src/fixers/mod.rs, scripts/memgrep/tests/cli.rs
Task: Wire C13 plus the fixers into lint_paths_with: scope lock → fix_page → write_gated; on refusal record 'unfixed' once per (page, reason) via the ledger; then the lock-only normalization path; re-lint; flags --unsafe-fixes, --diff, --show-fixes
Verify: CLI: a SAFE page gets fixed; a floor-error page stays byte-identical with exactly one ledger entry over 2 runs; --no-fix/--diff write nothing; on a scratch copy of the PROJECT memory, diff -r shows only the expected changes and validate is clean
Depends on: C21, C13, C14, C15, C16, C17, C18, C19
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:13+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:11+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 3HLI7DMK, I23YCEW7, 4G427D8M, 9SUZ48E8, QBU0HSM9, KSCAFSLD, RLD015QB, RUJQ7WSX per DSN035UN wave order
- 2026-10-06T20:03:31+0200 — column → todo by main-agent@ai-maestro-janitor. only blocker 3HLI7DMK complete Cleared blocked-by (--clear-blocker override).
- 2026-10-06T20:14:44+0200 — column → dev. plan v2 settled, work starts

## STATE

2026-10-05: blocked-by trimmed to the two cards still open (3HLI7DMK C21, I23YCEW7). C14 to C19 (4G427D8M, 9SUZ48E8, QBU0HSM9, KSCAFSLD, RLD015QB, RUJQ7WSX) were completed and archived on 2026-10-05 after review; the fixers are unit-tested and ready to wire. Wiring notes from that review: the unused-noqa fixer needs C21 before lint emits its code; the lint-ignore frontmatter line is still rebuilt with normalised spacing; a single-quoted description with a repeated phrase is not reported by lint.
2026-10-05 later: CORRECTION to the line above. The lint-ignore frontmatter line is no longer rebuilt with normalised spacing: e0d7dc50 reassembles it from its own bytes around the bracket span (test with an oddly spaced line). The other two wiring notes still stand; the single-quoted description gap is now card TRDD-GTP15HRC and the frontmatter terminator mismatch is TRDD-ZW0GUQCG.
2026-10-05 CORRECTION: C21 does NOT make the C19 has_code unused-noqa assert real. C21 emits unused-noqa in the lint command path only (apply_lint_config); lint_page_text, which has_code uses, is unchanged. Deciding where suppression lives (lint only, or lint_page_text and so the write gate) is carded as TRDD-KTD3N7H6 and is this card's to settle, since wiring fixers into lint needs emitter, fixer and gate to agree. Also for this card: C21 already calls fixers::fixer_for in-process per labelled finding to decide the safe-fix label, so the call site exists.
- 2026-10-05: From C21 (TRDD-3HLI7DMK, commit 453512bc, column ai_review): lint only dry-runs registered fixers to compute the safe-fix label; it applies none. When C22 wires them in it must test: (a) a deselected, ignored or noqa-suppressed rule is NOT autofixed; (b) a run refused for an unusable --config leaves every page byte-identical; (c) the pre-existing publish-globally autofix in lint_paths currently runs regardless of selection, decide whether that stays.
- 2026-10-05: C22 also owns the WM-LINT-10 wording defect: "safe-fix MUST NOT be printed for a fix the engine will not make" is only true once lint applies the fix.
2026-10-05: C21 follow-up 92663adf changed what C22 inherits. The safe-fix label is now a whole-rule answer per page with three conditions (see TRDD-3HLI7DMK STATE) and is deliberately withheld on a page where the fixer leaves any finding of that rule, and always for unused-noqa. Per-finding labels, and a label for unused-noqa, are C22's once it applies the fixes. The two "- 2026-10-05" lines above still stand.
2026-10-06: PLAN v2 (after two adversarial review rounds and two measurements; reports/board/20261006_201156+0200-c22-plan-measure.md and reports/board/20261006_201340+0200-c22-round2-measure.md). Fixers are OPT-IN behind a new flag --apply-fixes; plain lint is unchanged (it still runs only the publish-globally normalization, owner ruling TRDD-RY0IJBJI). This departs from this card's Verify line, which assumed default-on, because default-on would break current callers: scripts/memory_txn_cli.py counts findings on staged text as a delta gate, scripts/lib/memory_content_precheck.py detects chore work on two fixable rules, scripts/wikimem_bench.py would mutate the corpus it scores, scripts/hooks/post-edit-wikimem-lint.py would rewrite a page just edited. The callers of --apply-fixes are the dependents C30, C31, C32.
2026-10-06: Flag contract: --no-fix means no writes at all; default means normalization only; --apply-fixes means normalization plus registered safe fixers through write_gated. --apply-fixes with --no-fix is a usage error (exit 2). --diff is the dry run of --apply-fixes: prints the would-be change to stderr and writes nothing (no fix, no normalization, no ledger). The name is --apply-fixes, not --fix, so it cannot be read as the negation of --no-fix; TRDD-RY0IJBJI rejected a --fix flag for the normalization, which is a different thing and stays unconditional.
2026-10-06: Steps, one commit each, failing test first, then crate tests, clippy -D warnings and the full uv run pytest: S1 src/fixers/mod.rs record_unfixed(ledger, page, reason) appending page TAB reason once, and registered() listing rules with a fixer (test compares against the Fix::Safe entries of the rule table). S2 src/memory.rs plan_page_fix: eligible rules are enabled, fixable, have a fixer and have no suppressed finding; run fix_engine::fix_page; read-only gate check with pre_write::prepare_batch_gated; return new text or a refusal reason (not-converged, or gate plus the blocking codes). S3 flags --apply-fixes and --diff with the spec naming both in the same commit (tests/test_wikimem_spec_drift.py). S4 apply: write_gate::acquire, read, plan, pre_write::write_gated; on refusal one ledger line; ledger is written only under --apply-fixes. S6 manual check on scratch copies of the three scopes seeded with one finding per fixer-backed rule plus one gate refusal; the diff must be exactly those repairs and one ledger line.
2026-10-06: Tests required in S4: plain lint leaves a fixable page byte-identical (non-PROJECT fixture); a PROJECT-scoped, already-normalized refusal fixture; deselected, ignored and suppressed rules are not fixed; unusable config with --apply-fixes leaves pages byte-identical; exactly one ledger line after two runs; --apply-fixes with --no-fix exits 2; --diff alone writes nothing; a page-level unused suppression comment is removed while one inside an atom is refused and recorded (the gate fingerprints atom bodies including comments, src/pre_write.rs body_fingerprint); assertions by file bytes, not modification time. Unit tests that reach write_gate::acquire must set JANITOR_GLOBAL_STATE_DIR through scoped_env, or they write a lock file into the real state dir.
2026-10-06: DROPPED from this card: S5 (recomputing the safe-fix label from the plan) because it would change plain-lint output and add a gate check per page to a hook with a 4 to 5 s budget; the label keeps its TRDD-3HLI7DMK meaning (a safe fixer exists and clears the rule on the page) and may still be printed on a page where the gate would refuse the fix. --unsafe-fixes (no Fix::Unsafe rule exists; belongs to C43) and --show-fixes are also dropped. The ledger has no consumer yet. Write set extended by design/specs/wikimem-memgrep-spec.md (the flags and the WM-LINT-10 flag count). Wiring goes in cmd_lint_cli, not lint_paths_with, which has no config and is called with fixing on by about 35 unit tests. TRDD-EMZUVIBK also writes scripts/memgrep/tests/cli.rs and must not run in parallel with this card.
