---
trdd-id: DGBZVZPP
title: memgrep tests share process-wide state and fail at random under load
column: todo
status: tasked
created: 2026-10-04T14:01:11+0200
updated: 2026-10-05T09:45:00+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-04T14:01:11+0200
implementation-commits: [efa63d72, 0523af49, 19984aad]
---

# memgrep tests share process-wide state and fail at random under load

## Symptom

Rust tests of the bundled search tool failed once under machine load and passed on rerun, four different tests on 2026-10-04; the push gate runs this suite, so a release can be refused at random.

## Cause 1 (REPRODUCED)

The jev mock servers did one read and closed with unread request bytes, so the client could get a connection reset in place of the scripted reply. Fix: drain the whole request before replying. 60 of 60 runs clean at 32 threads after the fix.

## Cause 2 (INFERRED from reading the code, not reproduced)

Subprocess tests in tests/cli.rs all used the real global-state folder and queued on one shared lock with a 10 second timeout. Fix: each test thread gives its children a private state folder.

## Cause 3 (INFERRED from reading the code, not reproduced)

About 110 test sites set process-wide environment variables while tests run in parallel; five separate module mutexes serialized nothing across modules and readers took none. Fix: new module src/scoped_env.rs, a per-thread override in test builds, exactly std::env::var in release builds; six variable names, each with one production reader routed through it.

## Verification 2026-10-04

Clippy clean; 409 and 196 tests pass in parallel, serially, and in two repeat runs; release build has no warnings; with the override lookup disabled 16 unit tests fail, so the overrides are load-bearing; no assertion removed.

## Open items

- OPEN: eight unit tests set no override and still reach the real global-state folder in a normal run (three mem_reference tests, two memory tests, three xi9_cli tests; names in reports_dev/20261004_140007+0200-memgrep-isolation-verify.md section C).
- OPEN: nothing stops a new test from calling the process-wide setter again; add a clippy disallowed-methods entry for std::env::set_var and remove_var.
- OPEN: the jev tests still set process environment variables under their own lock (two helper sites); cache_hit_skips_network failure was assumed to share cause 1, not proven.
- OPEN: a test run with overrides ignored writes fixture pages into the real USER memory folder, which shows the tests can reach real state whenever an override is missed.
- The eight unit tests that still reach the real state folder: mem_reference reference_atom_wires_atom_body_and_target_page, reference_topic_second_call_is_a_no_op, reference_topic_wires_both_ends_in_one_call; memory new_page_public_project_creates_the_flag_and_the_symlink_in_one_write, scope_derives_the_path_and_the_env_override_relocates_the_root; xi9_cli update_lesson_desc_edits_footnote_without_stdin, update_lesson_desc_preserves_inline_body, update_lesson_desc_round_trips_props_only_footnote.
- CORRECTION to commit 0523af49's message: that cli children no longer write lock files in the real state folder was not measured separately; a normal run still created one new real lock file, attributed to unit tests, inconclusive.
- RESIDUE: a verification run with overrides disabled left two symlinks in the real USER memory folder and an untracked fixture folder under scripts/memgrep; removal awaits the owner.
2026-10-05 — column corrected: the open items on this card are code work, not review, and nobody is working them, so ai_review was a false claim. First step when picked up: a lint guard that forbids tests from changing process-wide environment (no such guard exists today).

## Approval log

- 2026-10-04T14:01:11+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
