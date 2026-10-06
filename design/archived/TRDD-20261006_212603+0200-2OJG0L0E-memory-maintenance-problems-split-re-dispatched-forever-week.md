---
trdd-id: 2OJG0L0E
title: Memory maintenance problems split re-dispatched forever, weekly verbatim re-arm, lint count spam, autorecall on notifications
column: complete
status: archived
created: 2026-10-06T21:26:03+0200
updated: 2026-10-07T00:25:05+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:26:03+0200
implementation-commits: [6e95fb5e, ecb8cc7f, 9ad6b9f6, 16d832ef, 6f513d53, 65e0b9bc, 47484d08, 13c9c336, 6099a561, 26c42b4e]
---

# Memory maintenance problems split re-dispatched forever, weekly verbatim re-arm, lint count spam, autorecall on notifications

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

Shipped in v3.8.0; GitHub issue #326 closed https://github.com/Emasoft/ai-maestro-janitor/issues/326#issuecomment-6025976532. Landed on main as 6e95fb5e,ecb8cc7f,9ad6b9f6,16d832ef,6f513d53,65e0b9bc,47484d08,13c9c336,6099a561,26c42b4e. Follow-ups for #326 landed on main: ticketed drift suppression, content-hash aware, with one detector keyed (package-manager-policy). It takes effect only after its PROJECT proposal is approved. KNOWN LIMITS: (1) the ticketed-block-hashes store is unlocked, so concurrent fires can race (named by a ponytail comment in the code); (2) a stale digest can hide an identical reopened finding if no fire ran between the ticket close and the reopen.
NEXT ACTION: move to complete once v3.8.1 is released and CI is green. Ships in v3.8.1.
FOLLOW-UP LOCATION: landed on main as 6e95fb5e,ecb8cc7f,9ad6b9f6,16d832ef,6f513d53,65e0b9bc,47484d08,13c9c336,6099a561,26c42b4e (the follow-up worktree is merged).


Source: GitHub issue Emasoft/ai-maestro-janitor#326 (opened 2026-10-02). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: Four problems were seen. The split chore is re-dispatched about twice a day on a scope it can never act on, verbatim atoms re-arm weekly, a lint count spams the heartbeat, and auto-recall runs on task notifications. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:26:03+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T00:25:05+0200 — COMPLETE by main-agent@ai-maestro-janitor. shipped in v3.8.1; acceptance items proven; self-approved by this standalone session.





## Acceptance

- [x] The split chore is no longer re-dispatched on a scope it can never act on (component over-cap pages: refusal recorded or re-tier acted on, pass continues to atom-level work). Proof: 3aacd967 (test in tests/test_memory_chore_claim_step.py pinning that an over-cap component page is skipped, not re-dispatched), 9ad6b9f6.
- [x] A verbatim atom that cannot be shortened is judged once, not weekly. Proof: 16d832ef; tests/test_split_atom_refusal.py::test_a_split_atom_refusal_suppresses_dispatch, test_the_refusal_never_expires_on_a_clock, test_editing_the_page_re_arms_the_chore.
- [x] An unchanged memgrep lint count no longer reaches heartbeat stdout. Proof: 6e95fb5e; tests/test_run_lint_stderr_echo.py::test_run_lint_with_echo_off_keeps_the_summary_off_stderr.
- [x] Auto-recall skips harness task notifications. Proof: ecb8cc7f; tests/test_autorecall_hook.py::test_on_harness_notification_prompt_is_noop.
- [x] A drift block whose finding has an open ticket is not re-printed (follow-up; one detector keyed). Proof: 6f513d53, 65e0b9bc, 47484d08, 13c9c336, 6099a561, 26c42b4e; tests/test_ticketed_drift_suppression.py::test_a_keyed_line_with_an_OPEN_ticket_is_suppressed and test_a_changed_block_resurfaces_while_the_ticket_is_open.
- [x] A closing comment on the issue names the commit and the release. Proof: https://github.com/Emasoft/ai-maestro-janitor/issues/326#issuecomment-6025976532
