---
trdd-id: POOBOHDM
title: A burn projection with no target falls through to exhausted and stuck
column: testing
status: tasked
created: 2026-10-05T22:11:17+0200
updated: 2026-10-10T16:43:22+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:17+0200
---

# A burn projection with no target falls through to exhausted and stuck

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

The stay-put branch for a projection covers only the case where every target is spent on the model in use. With no target at all the tick logs 'exhausted' and writes the stuck marker for what is only a projection. Read from the code; a first fix was dropped in review because it would also silence a real learned cap.

## Approval log

- 2026-10-05T22:11:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Corrections

2026-10-10 16:43. BUILT in this commit (wave 14 card 1). Premise read in scripts/oauth_rotator/rotator.py cmd_auto before the brief: an account-spent alternate lands in verdicts only, so a projection with no alternate, or with every alternate at its account limit, skipped the one stay-put block (which needs scoped_blocked) and reached stage 3: 'exhausted' plus the stuck marker. CHANGE: burn_gate.is_projection tells the slope projection from a learned-cap verdict; burn_only is now set for a projection only; a second stay-put block (burn_only and best is None and not degraded) writes no marker. A learned-cap verdict is a wall and still reaches stage 3, which is what the fix dropped on 2026-10-05 got wrong. TESTS (worker ran them red first for the first three): tests/test_oauth_rotator.py::test_cmd_auto_projection_with_no_alternates_stays_put_without_stuck_marker, ::test_cmd_auto_projection_with_only_account_spent_alternate_stays_put_without_stuck_marker, tests/test_burn_gate.py::test_is_projection_tells_a_guess_from_a_learned_cap; passing before and after: ::test_cmd_auto_learned_cap_verdict_with_no_alternates_still_marks_stuck and ::test_cmd_auto_projection_with_scoped_blocked_and_degraded_alternate_does_not_rotate. LIMITS: (1) FIELD CASE UNOBSERVED: the retained rotator logs (2026-10-10 09:08 to 16:37) hold 0 BURN lines. (2) NOT BUILT, by scope: a projection with only a degraded alternate still rotates onto it on a guess. (3) BEHAVIOUR CHANGE, dormant while cap learning is off: a learned-cap verdict whose alternates are all spent on the model in use no longer stays put, it goes to tier 1b like any real wall. (4) The degraded-alternate test was not shown to place its alternate in degraded (it passes either way); the main session did not check it. (5) is_projection matches a phrase the same module writes, pinned by its test. Worker report: reports/board/20261010_164240+0200-poobohdm-worker.md. Diff read whole by the main session before the commit.

## Acceptance

- [ ] A burn projection with no usage-confirmed target writes no stuck marker and no 'exhausted' line (pinned by the two stay-put tests; full gate on the fix commit green).
- [ ] A learned-cap verdict with no target still writes the stuck marker (pinned by its test).
- [ ] Field: a BURN projection line with no target seen in rotator.log followed by 'staying put' and no marker. FIELD CASE UNOBSERVED on 2026-10-10.
