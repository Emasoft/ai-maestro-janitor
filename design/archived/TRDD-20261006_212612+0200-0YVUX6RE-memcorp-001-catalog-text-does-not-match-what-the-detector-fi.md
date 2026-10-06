---
trdd-id: 0YVUX6RE
title: MEMCORP-001 catalog text does not match what the detector files under it and ticket wording is not enforced
column: complete
status: archived
created: 2026-10-06T21:26:12+0200
updated: 2026-10-06T23:46:25+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:26:12+0200
implementation-commits: [3b568247, 8f5a687b, 522f2d0c, fc73c8d2]
---

# MEMCORP-001 catalog text does not match what the detector files under it and ticket wording is not enforced

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

Shipped in v3.8.0; GitHub issue #336 closed https://github.com/Emasoft/ai-maestro-janitor/issues/336#issuecomment-6025980147. Landed on main as 3b568247,8f5a687b,522f2d0c,fc73c8d2. Follow-ups for #336 landed on main (8f5a687b, 522f2d0c, fc73c8d2): an incomplete ticket opens with a plain-bullet "Incomplete:" list of the unmet rules. Ticket wording is FLAGGED, NOT ENFORCED: this is option B, chosen under the owner's standing decide-and-proceed ruling and vetoable by the owner.
NEXT ACTION: none; the owner may still veto option B (flagged, not enforced).
FOLLOW-UP LOCATION: landed on main as 3b568247,8f5a687b,522f2d0c,fc73c8d2 (the follow-up worktree is merged).


Source: GitHub issue Emasoft/ai-maestro-janitor#336 (opened 2026-10-06). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The catalog entry describes link and structural damage, but the detector files every error severity lint finding under that code, including a merely short description. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:26:12+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-06T23:46:25+0200 — COMPLETE by main-agent@ai-maestro-janitor. shipped in v3.8.0, issue #336 closed.





## Acceptance

- [x] The MEMCORP-001 catalog text covers every ERROR-severity lint class the detector files under it. Proof: 3b568247; tests/test_issue_catalog.py::test_MEMCORP_001_text_covers_every_ERROR_lint_class_not_only_link_damage.
- [x] An incomplete ticket opens with a plain-bullet Incomplete list of the unmet rules. Proof: 8f5a687b, 522f2d0c, fc73c8d2; tests/test_issue_catalog.py::test_an_unfilled_marker_is_listed_as_unmet, test_a_located_code_without_where_is_listed_as_unmet, test_the_unmet_list_is_plain_bullets_not_task_boxes, test_the_unmet_list_survives_the_cap_with_many_unfilled_markers.
- [x] Ticket wording is flagged, not enforced (option B, chosen under the owner's decide-and-proceed ruling, vetoable). Proof: card STATE decision and the closing comment.
- [x] A closing comment on the issue names the commit and the release. Proof: https://github.com/Emasoft/ai-maestro-janitor/issues/336#issuecomment-6025980147
