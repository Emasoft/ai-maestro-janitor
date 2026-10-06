---
trdd-id: K2PEAYHR
title: TRDD id matcher cannot parse legacy v1 filenames so cards vanish from four detectors
column: complete
status: archived
created: 2026-10-06T21:25:44+0200
updated: 2026-10-06T23:45:54+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:44+0200
implementation-commits: [237cf471]
---

# TRDD id matcher cannot parse legacy v1 filenames so cards vanish from four detectors

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

Shipped in v3.8.0; GitHub issue #313 closed https://github.com/Emasoft/ai-maestro-janitor/issues/313#issuecomment-6025972585. Landed on main as 237cf471.
NEXT ACTION: none; shipped in v3.8.0 and the issue is closed.


Source: GitHub issue Emasoft/ai-maestro-janitor#313 (opened 2026-09-26). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The _TRDD_ID_RE pattern in trdd_common.py accepts only two filename shapes and rejects legacy v1 names with a UUID-style middle segment. Such cards have valid frontmatter but are invisible to four detectors. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:44+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-06T22:08:23+0200 — column → testing by main-agent@ai-maestro-janitor.
- 2026-10-06T23:45:54+0200 — COMPLETE by main-agent@ai-maestro-janitor. shipped in v3.8.0, issue #313 closed.

## Acceptance

- [x] The id matcher parses legacy v1 and bare v1-migrated filenames. Proof: 5ea63752 (v3.4.15); tests/test_trdd_common.py::test_extract_uid_legacy_uuid, test_extract_uid_bare_v1_migrated_shape, test_extract_uid_bare_shape_does_not_shadow_legacy_uuid.
- [x] A card with a bare legacy filename is counted by the board instead of vanishing. Proof: tests/test_trdd_common.py::test_bare_shape_card_is_counted_by_the_board.
- [x] The documentation side is aligned. Proof: 237cf471 (v3.8.0).
- [x] A closing comment on the issue names the commit and the release. Proof: https://github.com/Emasoft/ai-maestro-janitor/issues/313#issuecomment-6025972585
