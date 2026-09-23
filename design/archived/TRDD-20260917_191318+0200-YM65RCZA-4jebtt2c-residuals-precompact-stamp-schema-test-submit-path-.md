---
trdd-id: YM65RCZA
title: 4JEBTT2C residuals - PreCompact stamp schema test, submit-path still_wanted citation, stamp-name literal, private cross-module reader
column: superseded
created: 2026-09-17T19:13:18+0200
updated: 2026-09-23T06:03:21+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: refactor
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-17T19:13:18+0200
superseded-by: [RAEGS1D5]
---

# 4JEBTT2C residuals - PreCompact stamp schema test, submit-path still_wanted citation, stamp-name literal, private cross-module reader

(1) add a test that runs pre-compact-handoff.py's real writer for precompact-last-trigger.json and asserts terminal_trigger._read_landed_stamp(path, "json_written_at") returns its written_at epoch float (today only a hand-built JSON is tested); (2) cite or fix: does inject_until_sent's "our command is present in the field, submit" branch re-ask still_wanted before Enter (the trace at 935/991 covers the type path only); (3) compact_trigger.py hardcodes the literal "precompact-last-trigger.json" duplicated from pre-compact-handoff.py's _LAST_TRIGGER_FILENAME — add a one-line equality test or a shared constant; (4) terminal_trigger._read_landed_stamp is underscore-private but called from compact_trigger.py — rename to public. Origin: TRDD-4JEBTT2C final adversarial review 2026-09-17.

## Approval log

- 2026-09-17T19:13:18+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-09-17T20:00:00+0200 — worker (this session) implemented items 1, 2, 4 (item 3 owned by TRDD-PH8SAQKS worker, scripts/compact_trigger.py). Files: scripts/lib/terminal_trigger.py (rename _read_landed_stamp -> read_landed_stamp + a why-commented backward-compat alias `_read_landed_stamp = read_landed_stamp`), tests/test_precompact_last_trigger_stamp_schema.py (new — runs the real pre-compact-handoff.py writer end-to-end and asserts read_landed_stamp parses its written_at exactly), tests/test_terminal_trigger_readback.py (new test test_already_typed_branch_is_ALSO_cancelled_by_still_wanted — item 2: cited scripts/lib/terminal_trigger.py:935-940 (still_wanted checked unconditionally at loop top, before the pane read at :955 that decides already_typed at :984) as ALREADY covering the already-typed submit branch, no code fix needed, only a test). Gate: 121 passed 1 skipped (pytest tests/test_terminal_trigger.py tests/test_terminal_trigger_readback.py tests/test_precompact_last_trigger_stamp_schema.py -q); ruff check scripts tests -> All checks passed; mypy scripts/ --ignore-missing-imports -> Success: no issues found in 504 source files; pyright scripts/lib/terminal_trigger.py + the 3 test files -> 0 errors, 0 warnings, 0 informations. Reconciliation note for the TRDD-PH8SAQKS worker: scripts/compact_trigger.py:236 calls terminal_trigger._read_landed_stamp(...) -- still works via the alias; update to read_landed_stamp when that worker's own edit lands, then the alias may be deleted.
- 2026-09-23T06:03:21+0200 — SUPERSEDED by claude-main. compact_trigger.py and on-stop-proactive-compact.py deleted by commit 54ea73bc (TRDD-RAEGS1D5); the /compact race this card guarded cannot occur.
