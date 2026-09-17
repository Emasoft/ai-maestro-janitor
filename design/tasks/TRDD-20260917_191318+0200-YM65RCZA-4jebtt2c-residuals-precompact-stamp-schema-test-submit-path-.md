---
trdd-id: YM65RCZA
title: 4JEBTT2C residuals - PreCompact stamp schema test, submit-path still_wanted citation, stamp-name literal, private cross-module reader
column: backburner
created: 2026-09-17T19:13:18+0200
updated: 2026-09-17T19:13:18+0200
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
---

# 4JEBTT2C residuals - PreCompact stamp schema test, submit-path still_wanted citation, stamp-name literal, private cross-module reader

(1) add a test that runs pre-compact-handoff.py's real writer for precompact-last-trigger.json and asserts terminal_trigger._read_landed_stamp(path, "json_written_at") returns its written_at epoch float (today only a hand-built JSON is tested); (2) cite or fix: does inject_until_sent's "our command is present in the field, submit" branch re-ask still_wanted before Enter (the trace at 935/991 covers the type path only); (3) compact_trigger.py hardcodes the literal "precompact-last-trigger.json" duplicated from pre-compact-handoff.py's _LAST_TRIGGER_FILENAME — add a one-line equality test or a shared constant; (4) terminal_trigger._read_landed_stamp is underscore-private but called from compact_trigger.py — rename to public. Origin: TRDD-4JEBTT2C final adversarial review 2026-09-17.

## Approval log

- 2026-09-17T19:13:18+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
