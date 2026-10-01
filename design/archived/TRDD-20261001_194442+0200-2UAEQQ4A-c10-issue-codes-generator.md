---
trdd-id: 2UAEQQ4A
title: C10 — issue codes generator
column: complete
status: archived
created: 2026-10-01T19:44:42+0200
updated: 2026-10-01T20:34:08+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:44:42+0200
blocked-by: []
pre-block-column: 
blocker-probe: [trddgrep, why, 2UAEQQ4A]
blocker-holds-if: not-match:READY
implementation-commits: [10293add]
---

# C10 — issue codes generator

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C10, wave W1.

Writes (exclusive): scripts/build_issue_codes.py (renamed from issue_codes_gen.py, whose name clashed with the generated lib module), tests/test_issue_codes_spec.py, docs/ISSUE-CODES.md, scripts/issue_catalog_doc.py, src/rules_gen.rs (generated)
Task: Generator with --write/--check; emits rules_gen.rs, the docs, and scripts/lib/issue_codes_gen.py
Verify: --write run twice gives no diff; --check exits 0; test_issue_catalog.py still passes
Depends on: C01, C02
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:44:42+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:45:41+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on LKOUJC76, 622ROA5F per DSN035UN wave order
- 2026-10-01 — DECISION (review of wave 0, finding 1): rules_gen.rs emits ONLY rows whose emitter is "memgrep" (their severity is ERROR/WARN/INFO and fits the frozen Rule.sev: Severity); scripts/lib/issue_codes_gen.py emits EVERY row. The frozen Rule type is not changed. Fix enum variant is NoFix (not None).
- 2026-10-01T19:58:34+0200 — column → dev by main-agent@ai-maestro-janitor. blockers C01/C02 complete; dispatched 2026-10-01 Cleared blocked-by (--clear-blocker override).
- 2026-10-01 — tools-rule exceptions reported by the C10 workers: guarded Python string-replace on module docstrings/constants fastedit cannot target, and fastedit create --force on a just-created file. Recorded, not repeated; the stub/non-symbol amendment is pending on DSN035UN.
- 2026-10-01T20:34:08+0200 — COMPLETE by main-agent@ai-maestro-janitor. generator landed 10293add, verified..

## Acceptance checklist

- [x] build_issue_codes.py --write/--check: --check exits 0 on the committed tree (main-verified 2026-10-01 on the combined tree)
- [x] rules_gen.rs holds only memgrep-emitter rows; issue_codes_gen.py holds every row; Rule type unchanged; memgrep 365+196 tests pass (main-verified 2026-10-01 on the combined tree)
- [x] issue_catalog.py reads the generated registry; ruff/mypy/pyright clean; full pytest 17714 passed (main-verified 2026-10-01 on the combined tree)
