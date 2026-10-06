---
trdd-id: TMZRFMZL
title: One command that toggles auto-rotation on both the janitor flag and the server flag file
column: complete
status: archived
created: 2026-10-06T21:25:55+0200
updated: 2026-10-06T23:45:57+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:55+0200
implementation-commits: [33525949, cb236ce6]
---

# One command that toggles auto-rotation on both the janitor flag and the server flag file

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

Shipped in v3.8.0; GitHub issue #321 closed https://github.com/Emasoft/ai-maestro-janitor/issues/321#issuecomment-6025974013. Landed on main as 33525949,cb236ce6.
NEXT ACTION: none; the owner may still veto the DECISION above (both-sides semantics).
DECISION (2026-10-06, taken under the owner's standing "decide yourself and proceed" ruling, owner may veto): ship the current both-sides semantics. With rotation on at both sides, both stay on and the ai-maestro server's ownership lease decides which side rotates. This is stated in the release notes.


Source: GitHub issue Emasoft/ai-maestro-janitor#321 (opened 2026-09-29). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The owner wants a single janitor command that enables or disables auto-rotation on both sides at once, the janitor opt-in flag and the ai-maestro server flag file, so a half-state cannot be reached. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:55+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-06T23:45:57+0200 — COMPLETE by main-agent@ai-maestro-janitor. shipped in v3.8.0, issue #321 closed.





## Acceptance

- [x] One command turns auto-rotation on or off on both sides (janitor opt-in flag and ai-maestro server flag file). Proof: 33525949, cb236ce6; tests/test_oauth_rotation_toggle.py::test_on_sets_both_flags and test_off_clears_both_flags.
- [x] A half-state cannot be reached: disagreeing sides are fixed to the requested state and a failed second write undoes the first. Proof: tests/test_oauth_rotation_toggle.py::test_disagreeing_sides_are_fixed_to_requested_state, test_second_write_failure_undoes_first, test_off_failure_restores_janitor_flag.
- [x] A closing comment on the issue names the commit and the release. Proof: https://github.com/Emasoft/ai-maestro-janitor/issues/321#issuecomment-6025974013
