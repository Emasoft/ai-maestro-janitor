---
trdd-id: IRBTX41Q
title: Privacy scan SSN pattern false-positives on Cargo.lock hex checksums and blocks every dependency bump
column: complete
status: archived
created: 2026-10-06T21:25:49+0200
updated: 2026-10-07T07:01:43+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:49+0200
---

# Privacy scan SSN pattern false-positives on Cargo.lock hex checksums and blocks every dependency bump

Source: GitHub issue Emasoft/ai-maestro-janitor#316 (opened 2026-09-28). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The US SSN pattern has optional separators, so digit runs inside the 64-hex checksums of a Cargo.lock match it. Any commit that adds checksums is blocked. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:49+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T07:01:43+0200 — COMPLETE by main-agent@ai-maestro-janitor. resolved, evidence in STATE.

## STATE

2026-10-07 already fixed before this card was worked: the staged privacy scan suppresses PII shapes in named lockfiles by file name, wherever they sit, and tests/test_staged_privacy_scan.py::test_cargo_lock_checksum_does_not_block uses the exact checksum line from GitHub issue 316 (reported path scripts/memgrep/Cargo.lock). Tightening the SSN pattern instead broke three tests that guard the deliberate design (a hex run outside a lockfile still blocks), so it was not done. Issue 316 is closed.

## Acceptance checklist

- [x] The symptom is gone: tests/test_staged_privacy_scan.py::test_cargo_lock_checksum_does_not_block uses the exact checksum line from GitHub issue 316 and passes; named lockfiles are suppressed by file name; pytest 18087 passed, 2 skipped on main at the B3 merge; issue 316 closed.
