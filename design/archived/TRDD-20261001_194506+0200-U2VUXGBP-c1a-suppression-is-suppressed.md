---
trdd-id: U2VUXGBP
title: C1A — suppression is_suppressed
column: complete
status: archived
created: 2026-10-01T19:45:06+0200
updated: 2026-10-03T14:20:25+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:06+0200
blocked-by: []
pre-block-column: 
blocker-probe: [trddgrep, why, U2VUXGBP]
blocker-holds-if: not-match:READY
implementation-commits: [62d7536c]
---

# C1A — suppression is_suppressed

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C1A, wave W1.

Writes (exclusive): scripts/lib/suppression.py, tests/test_suppression.py
Task: is_suppressed(code,path) with family, prefix, name, per-file-ignores and expiring [[suppress]]
Verify: Unit tests; workflow-security behaviour unchanged (existing tests pass)
Depends on: C02
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:06+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:00+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on 622ROA5F per DSN035UN wave order
- 2026-10-01T19:52:44+0200 — column → dev by main-agent@ai-maestro-janitor. Python card with no dependency on the C02 Rust scaffold (review finding 10); dispatched 2026-10-01 Cleared blocked-by (--clear-blocker override).
- 2026-10-01 — do NOT archive yet: a malformed .janitor.toml makes is_suppressed raise. Owned by C24 (wave-1 review finding 2): C24 catches it in the ledger/drift path, emits CONFIG-001 and treats nothing as suppressed. Close C1A once that is recorded on C24. See DSN035UN 'C1A/C1C/C1D open items'.
- 2026-10-03: C24 ownership of the malformed .janitor.toml catch (CONFIG-001, nothing suppressed) is recorded on TRDD-8524H5V1 (REQUIREMENT and OWNS lines); close condition met.
- 2026-10-03T13:50:36+0200 — column → testing by main-agent@ai-maestro-janitor. close condition met
- 2026-10-03T13:50:51+0200 — column → ai_review by main-agent@ai-maestro-janitor. close condition met
- 2026-10-03T13:51:09+0200 — column → human_review by main-agent@ai-maestro-janitor. close condition met
- 2026-10-03T14:20:25+0200 — COMPLETE by main-agent@ai-maestro-janitor. acceptance checklist complete.

## Acceptance criteria

- [x] Unit tests in tests/test_suppression.py pass (commit 62d7536c)
- [x] Malformed .janitor.toml handling (CONFIG-001, nothing suppressed) is owned and recorded on TRDD-8524H5V1
