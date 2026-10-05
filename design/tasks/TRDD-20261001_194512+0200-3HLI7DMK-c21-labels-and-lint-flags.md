---
trdd-id: 3HLI7DMK
title: C21 — labels and lint flags
column: dev
status: tasked
created: 2026-10-01T19:45:12+0200
updated: 2026-10-05T02:12:30+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:12+0200
blocked-by: []
pre-block-column: 
blocker-probe: [trddgrep, why, 3HLI7DMK]
blocker-holds-if: not-match:READY
---

# C21 — labels and lint flags

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C21, wave W2.

Writes (exclusive): src/memory.rs, scripts/memgrep/tests/cli.rs
Task: Labels ' (FAMILY-NNN · safe-fix)' before the anchor; flags --select, --extend-select, --ignore, --statistics, --exit-zero, --output-format json, --config, --isolated, wired to C11 and C12; emit WMSUP-*
Verify: CLI tests per flag; pytest feeds a labelled line to _LINE_RE and the 4 precheck regexes; wikimem-syntax.py summary still prints
Depends on: C20, C11, C12
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:12+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:09+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on BHIS99XE, OWGEOJ0D, 7SMPCPNT per DSN035UN wave order
- 2026-10-01 — DESIGN NOTE (review finding 4): print the safe-fix label on a finding only when the registered fixer would actually change that page (e.g. atom-unquoted-desc over 200 chars has no fix) — a label that promises a fix the engine will not make is a lie.
- 2026-10-05T01:56:08+0200 — column → todo by main-agent@ai-maestro-janitor. its only open blocker C20 (BHIS99XE) was completed on 2026-10-05; OWGEOJ0D and 7SMPCPNT were already complete Cleared blocked-by (--clear-blocker override).
- 2026-10-05T01:56:39+0200 — column → dev by main-agent@ai-maestro-janitor. a worker starts the implementation on 2026-10-05 per plan DSN035UN card C21

## STATE

2026-10-05: blocked-by trimmed to BHIS99XE (C20, in ai_review). OWGEOJ0D (C11) and 7SMPCPNT (C12) are complete and archived, so listing them raised GRAPH-DANGLING-BLOCKER. Note for this card: the C19 unused-noqa fixer tests carry a has_code assert that cannot fail until this card makes lint emit unused-noqa; re-run them then (see archived TRDD-RUJQ7WSX).
2026-10-05 later: column dev; C20 (BHIS99XE) is complete and archived, blocked-by is empty. One worker is implementing the card from the DSN035UN plan text. NEXT ACTION: when the worker reports, the main agent reads the full diff, runs cargo test and clippy on a still tree with exit codes read directly, runs the pytest files named in Verify, then re-runs the C19 fixer tests with a real has_code oracle.
2026-10-05 02:1x: first implementation is in the working tree, uncommitted (patch copy: reports_dev/20261005-c21-wip.patch). Measured by the main agent: cargo test 423 unit and 205 cli pass, clippy -D warnings exit 0; full Python suite 17900 passed, 1 failed: tests/test_wikimem_spec_drift.py::test_every_flag_is_named_in_the_spec[lint], because design/specs/wikimem-memgrep-spec.md does not name the eight new flags. An independent code review (reports/memgrep-fixers, c21-code-review) found no blocker and five should-fix.
2026-10-05 WRITES AMENDED, with reasons, before the files are touched: (1) design/specs/wikimem-memgrep-spec.md, the spec-drift test requires every lint flag to be named there; (2) scripts/memgrep/src/main.rs, lint help text only; (3) a new pytest file under tests/ for this card's own Verify line (a labelled line against _LINE_RE and the four precheck regexes); (4) scripts/memgrep/src/fixers/unused_noqa.rs, test module only: its has_code unused-noqa assert becomes real now that lint emits the code (file of archived card RUJQ7WSX, whose checklist names this as the limit C21 lifts). The original Writes list (memory.rs, tests/cli.rs) could not satisfy the card's own Verify line.
2026-10-05 DECISIONS for the second pass, each from a fact read in source: (a) an explicit --config that is missing, unreadable or malformed stops with exit 2 through the strict lint_config::load; this follows load_lenient's own doc comment in lint_config.rs (strict load is for explicit --config) and REFINES the plan card line that says C21 uses load_lenient: a DISCOVERED malformed file keeps load_lenient, CONFIG-001 on stderr, defaults, exit 1. (b) a command-line selector that matches zero registered rules (and is not ALL) stops with exit 2; the same in a config file is a stderr warning and is ignored, so a config written for a newer memgrep does not break an older one. (c) NOT in this card: unused-noqa judging cross-page selectors; the predicate page_decidable is private to the fixer module and belongs in the registry, to be carded. (d) the summary line names a config error when one gated the run. Facts checked for the release risk: no .janitor.toml exists in the home directory, in ~/.claude or in this repository, and no page in the PROJECT or USER memory carries a noqa comment or a lint-ignore key, so default-on discovery and suppression change nothing on this machine today; the Rust lint table accepts a superset of the keys scripts/lib/suppression.py reads.
2026-10-05 heartbeat-caller fact, read in source: scripts/wikimem_syntax_lint.py run_lint returns (returncode, stdout, findings) and echoes memgrep's stderr; the heartbeat detector scripts/detectors/wikimem-syntax.py calls it at lines 122 and 414 as _code, _stdout, findings and DISCARDS the exit code. So a discovered malformed .janitor.toml (exit 1, CONFIG-001 on stderr) is not a standing alarm for the heartbeat: findings are still reported with built-in defaults and the error line goes to stderr only. The wrapper's own main() returns memgrep's code, so a human or script calling wikimem_syntax_lint.py does see exit 1. Two design limits of this card's first pass, NOT fixed here, carded as TRDD ids below: discovery starts from the FIRST linted path only, and the detector lints three scope roots in one call, so one root's config would apply to all three; and noqa is honoured by the lint command only, not by lint_page_text, so the write gate and the C19 fixer oracle (has_code unused-noqa) still cannot see it: the C19 limit is NOT lifted by this card.
The two cards named above: TRDD-57KAZJI7 (lint config policy) and TRDD-KTD3N7H6 (suppression scope: lint versus write gate versus fixer oracle; also carries the cross-page unused-noqa question).
