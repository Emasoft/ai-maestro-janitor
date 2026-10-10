---
trdd-id: ADIGRD0T
title: The janitor nudges an idle main agent that has pending work
column: testing
created: 2026-09-24T08:11:47+0200
updated: 2026-10-10T10:34:29+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T08:11:47+0200
blocked-by: []
pre-block-column: 
blocker-probe: trddgrep --design-dir "$(git rev-parse --show-toplevel)/design" show 6ESS2MGE --porcelain | cut -f3
blocker-holds-if: not-match:^(complete|completed|cancelled|superseded|published|live|failed|live_auditing)$
status: tasked
implementation-commits: [fb6bb844, 828c884f]
release-via: publish
---

# The janitor nudges an idle main agent that has pending work

owner directive of 2026-09-24 (verbatim in TRDD-WZKFSQ2N): "nudging the main agent when it is idle to resume working, telling him the pending TRDDs, the uncommitted work...". Today trdd-reminder fired 15 times this week and dirty-tree 29 times (ledger counts, 2026-09-17 to 2026-09-24), all into the ledger only (both are in dispatch.py's _ADVISORY_DETECTORS). Nothing types into an idle session that has pending work. Related: TRDD-I63GQJTK (in-flight workers look stalled), TRDD-L32WC0H7 (the liveness nudge). The routing decision (agent-facing resume prompt vs owner-facing heartbeat) is tracked on TRDD-6ESS2MGE only.

## Approval log

- 2026-09-24T08:11:47+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-10 04:58 UNBLOCKED (board drain). The routing decision this card waited on is recorded on TRDD-6ESS2MGE: under the owner's rule of 2026-09-27 a finding reaches the agent when the agent must act, and an idle agent with pending work is such a case, so the nudge is AGENT-FACING (a prompt into the idle session), not an owner-facing heartbeat line. Before building, compare with TRDD-HYTKG53C (a quiet heartbeat never re-engages a session that sits idle with pending work; in testing) and TRDD-C0RSMPRG (the resume injection was not done 107 times of 130): this card may already be covered by the first and depends on the second working.
- 2026-10-10T04:58:02+0200 — column → todo by main-agent@ai-maestro-janitor. the routing decision it waited on is recorded on 6ESS2MGE Cleared blocked-by (--clear-blocker override).
2026-10-10 10:14 SCOPED (board drain, wave 5 card 1; main session read scripts/dispatch.py lines 4130 to 4232 and TRDD-HYTKG53C). The nudge this card asks for ALREADY EXISTS: _phase_keep_going_nudge emits [janitor-resume] 'continue your pending task (keep-going mode)' with the open board, the open-issues count, pending background agents and the owner's last message. FIELD INSTANCE of this card's own case: this session, idle while a gate ran, received that line at 09:30 and 10:10 on 2026-10-10 (dispatch.log 10:09:55 'keep-going: nudge emitted') and resumed work on it both times. Whether the nudge reaches an idle pane while the owner types elsewhere is TRDD-HYTKG53C's check, and whether the daemon's resume injection lands is TRDD-C0RSMPRG's; neither is this card's. WHAT IS MISSING against the owner's words of 2026-09-24 ('telling him the pending TRDDs, the uncommitted work'): the nudge never mentions uncommitted work. REMAINING BUILD: one clause in the nudge giving the count of uncommitted files in the project's working tree when it is not zero, with one test; nothing else.
- 2026-10-10T10:12:45+0200 — column → dev. one clause to build: uncommitted files in the keep-going nudge
2026-10-10 10:18 BUILT in fb6bb844 (1 lean-worker, 0.13 million tokens; whole diff read by the main session): _uncommitted_work_bit in scripts/dispatch.py, appended in the same tuple as the board and open-issues bits of _phase_keep_going_nudge, so it rides only on a nudge already being emitted; one read-only git status through git_utils.run_git_readonly, 5 s timeout; non-repo, failure or timeout gives no clause and one log line. PINNING TESTS in tests/test_dispatch_phases.py, on real temporary git repos: test_uncommitted_work_bit_counts_dirty_files_in_a_real_repo, test_uncommitted_work_bit_is_empty_on_a_clean_repo, test_uncommitted_work_bit_is_empty_outside_a_git_repo. The worker did not show the first test failing before the change (it calls a function that did not exist, so it could not pass). The worker reported ruff, mypy, pyright at exit 0 and 239 tests passing in that file plus the optional-locks guard; the full gate on fb6bb844 writes reports/board/gate-fb6bb844.txt and had not reported when this was written. CORRECTIONS to the 10:14 line, from the review of 7ea90b11: 'the nudge never mentions uncommitted work' rested on lines 4130 to 4232 only; the worker was told to read the whole phase and to stop if such a clause existed, and it built instead (its report: docs_dev/20261010_101625+0200-adigrd0t-uncommitted-clause.md, gitignored; the main session did not read the phase's head itself). 'resumed work on it both times' overstates 09:30, when the session only replied that it was waiting on a gate. The field instance shows the nudge is emitted and acted on in the pane where the cron fires; it does not show a stalled session being re-engaged (that is TRDD-HYTKG53C's). NOT WEIGHED: the dirty-tree detector is advisory and ledger-only by choice; this clause puts the count in front of the agent only when it is idle with a nudge already due. FIELD CHECK after a release: a keep-going nudge received while the tree is dirty carries the clause.
- 2026-10-10T10:17:28+0200 — column → testing. built in fb6bb844; waits for the full gate, then a release for its field check
2026-10-10 10:36. GATE GREEN on fb6bb844 (ruff, mypy, pyright exit 0; 18286 passed, 2 skipped; reports/board/gate-fb6bb844.txt). FIX 828c884f from the review of fb6bb844, taken as a blocker by the main session: the clause no longer says 'commit or finish them'; it reads 'N uncommitted entr(y/ies) in the working tree (git status; untracked files included, they may not be yours)', and the first test asserts no commit instruction is present. CORRECTION, a false statement in the 10:18 line and in the message of fb6bb844: 'non-repo, failure or timeout gives no clause and one log line' is wrong; only an EXCEPTION (a timeout, a missing git) writes the log line; a non-zero exit from git (a directory that is not a repository) returns no clause silently. RECORDED, NOT BUILT (wave 5 cap): the count is git status entries, not files (an untracked directory is one line; gitignored work is invisible); state.project_root() may not be the git root of the files being edited in a folder that holds several repositories; when no other bit is present a dirty tree replaces the generic 'if the work is finished say so' message with this clause; no test covers the call site or that a suppressed nudge stays suppressed on a dirty tree; the clean-repo and non-repo tests cannot fail alone, and the dirty-repo test depends on the fixture directory holding nothing else untracked and on no global git excludes; the cost of one git status per emitted nudge is unmeasured; git_utils.run_git_readonly's contract was not read by the main session. The gate on 967c6bac (which contains 828c884f) writes reports/board/gate-967c6bac.txt and had not reported when this was written.
