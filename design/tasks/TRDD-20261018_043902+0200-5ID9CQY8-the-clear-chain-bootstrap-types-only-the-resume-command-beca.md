---
trdd-id: 5ID9CQY8
title: The clear chain bootstrap types only the resume command because the cron survives a clear
column: dev
status: tasked
created: 2026-10-18T04:39:02+0200
updated: 2026-11-15T15:59:18+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-18T04:39:02+0200
parent-trdd: K9AHY1ZB
derived: true
implementation-commits: [aeb41b33, 47cbcbc3]
---

# The clear chain bootstrap types only the resume command because the cron survives a clear

## What

Item C5 of TRDD-K9AHY1ZB Release 2, never built and never carded until 2026-10-18: the clear chain's bootstrap becomes `(RESUME_CMD,)` because crons survive `/clear`; the reload triggers keep `/janitor-arm`.

## Measured 2026-10-18

- `scripts/clear_trigger.py:82` still reads `_BOOTSTRAP_CMDS: tuple[str, ...] = (ARM_CMD, RESUME_CMD)`, exported as `BOOTSTRAP_CMDS` for other triggers via `spawn_shrink_chain`. No commit names C5.
- Evidence that a cron survives `/clear`: after the 2026-10-18 03:44 janitor clear, the re-arm's `CronDelete` of the prior heartbeat id 19df26ee SUCCEEDED ("Cancelled job 19df26ee"), so that cron still existed after the clear. `scripts/handoff_clear_verify.py` labelled the same id change "destroyed by /clear, recreated by re-arm", which the successful delete contradicts. That success is evidence because CronDelete fails not-found for an id that no longer exists (the janitor-arm skill relies on exactly that), and the id cannot have been re-created: the SessionStart self-check only re-plumbs when no heartbeat exists and would store a new id. One observation only, on Claude Code 2.1.302; a later Claude Code version re-opens the question.
- 2026-10-18 08:10 clear (Jev compaction, session 77e6aba3 to 33ef3d73): the re-arm's CronDelete of the prior heartbeat id 590dbe30 SUCCEEDED ('Cancelled job 590dbe30.'), so that cron survived this /clear too; handoff_clear_verify.py again reported it as 'destroyed by /clear, recreated by re-arm' (reports/continuity-build/20261018_081056+0200-handoff-clear-verify.md). Second observation after the 03:44 one; box 1 asks for at least two more beyond 03:44, so one more is owed.
2026-10-19 23:15 — WORK ITEM box 4 LANDED (commit aeb41b33): scripts/handoff_clear_verify.py now extracts the re-arm's successful CronDelete of the prior heartbeat id from the transcript (requires tool_use_id pairing with a CronDelete tool_use whose input.id equals the prior id, plus the result-text match 'Cancelled job <id>') and stores the matched id as prior_cron_deleted in the after-snapshot; compute_verdicts reports 'SURVIVED the clear' only when the matched id equals b_id, neutral otherwise — a surviving cron is no longer mislabelled 'destroyed by /clear, recreated by re-arm'. Module docstring reworded to the conditional classification. New negative test (input.id mismatch → guard-off) added; three adversarial review rounds, final APPROVE no blocking findings; both round-2 MINOR items closed. Gate green: pytest 65 + 46 consumer tests, ruff/mypy/pyright clean. Worker report: reports_dev/20261019_204500+0200-5id9cqy8-box4-handoff-clear-verify.md (ai-maestro#168).
- 2026-11-15 14:12 clear (token-meter clear of session 46a3bf7f, new session 5d861615), Claude Code 2.1.325: the bootstrap typed /janitor-arm; its arm_prepare printed prior-cron-id=dda92b6d sweep=no and the CronDelete of dda92b6d SUCCEEDED ('Cancelled job dda92b6d.'), so the heartbeat cron survived this /clear as well. Third observation (after 03:44 and 08:10), on a Claude Code version 23 releases later than 2.1.302. SessionStart logged 'armed; source=clear keeps the live cron -> no re-arm' at 14:12:33 (.janitor/logs/session-start.log), so the hook already assumes the cron survives a clear; the typed /janitor-arm then replaced a live cron for one extra billed turn.

## Acceptance

- [x] Confirm on at least two more clears that the prior heartbeat cron is still listed after `/clear` (CronList before the bootstrap), or drop this card if it is ever gone.
- [ ] The clear chain types only `/janitor-resume`; every reload trigger that composes on `BOOTSTRAP_CMDS` still re-arms (it must keep `/janitor-arm` or compose its own). After this change a session whose cron DID die at a clear depends on the SessionStart heartbeat self-check and the armed.flag re-plumb; a test or a log line must show that backstop fires.
- [ ] A dry-run keystroke-plan test for the clear chain and for each reload trigger fails before and passes after.
- [x] `handoff_clear_verify.py` no longer reports a surviving cron as destroyed.
- [ ] Full gate green (ruff, mypy, pyright, pytest).

## Approval log

- 2026-10-18T04:39:02+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Plan for boxes 2 and 3

2026-11-15T15:34+0100 PROPOSAL (main agent, under the 2026-10-09 decide-yourself mandate; the harness review of the proposal turn never arrived, advisor consulted instead): clear_bootstrap() in scripts/clear_trigger.py returns [RESUME_CMD], or ['/goal <goal>'] for an unmet goal, never ARM_CMD first (error fallback included). BOOTSTRAP_CMDS stays (ARM_CMD, RESUME_CMD) for the reload chains (reload_trigger.py:149, reload_skills_trigger.py:133), because a plugin reload may drop the cron. All five clear callers already go through clear_bootstrap (dispatch.py:3919, external_handoff_clear.py:602, hooks/on-stop-token-meter.py:186, clear_trigger.py:136 and :1473). Comment at clear_trigger.py:79-81 and the plan_clear/clear_bootstrap docstrings restate the measured reason. Tests written, not run (pre-push only): every test naming clear_bootstrap, plan_clear, is_goal_bootstrap, BOOTSTRAP_CMDS or a literal /janitor-arm for a clear chain is updated (incl. test_dispatch_phases.py:4187, test_clear_preserves_live_subagent.py:206, test_token_meter_logs_every_turn.py:96-98); new keystroke-plan test: clear phase B is ['/janitor-resume'] (or ['/goal ...']) while both reload plans start with /janitor-arm. Backstop (box 2): the SessionStart heartbeat self-check reminder for source=clear and the armed.flag re-plumb need a test. Advisor items: (a) timing, the arm turn was a ~25 s buffer before the resume stub (crumbs 14:12:37 and 14:13:02; handoff stamped 14:12:36), so check nothing the resume phase reads is still being written when /janitor-resume lands first; (b) renewal, every clear re-created the cron and reset its 7-day expiry and armed-at stamp, so after this change [janitor-renew] is the only renewal and that path must be tested; (c) handoff_clear_verify.py loses its SURVIVED evidence (the re-arm's CronDelete); re-source it from a [janitor-heartbeat] prompt in the new session with no CronCreate before it, or delete the SURVIVED branch and its test for clears if the verifier snapshots too early. Strongest reason not to: a Claude Code build that drops crons on /clear would then depend on the model obeying the SessionStart reminder.
2026-11-15T15:56+0100 BUILT (uncommitted at write time; commit named in implementation-commits; the dispatch.py and test line numbers below were main-verified at 15:57): clear_bootstrap returns CLEAR_BOOTSTRAP_CMDS = ('/janitor-resume',) or ['/goal <goal>']; BOOTSTRAP_CMDS (arm, resume) kept for the reload chains; skills janitor-handoff-and-clear and janitor-compact-context updated. Advisor items: (a) no race found by reading the code (summary-hold check dispatch.py:5530-5537 returns before _phase_clear_resume at :5562; only _phase_clear_resume removes resume-after-clear.flag, after emitting the cue); whether a typed slash command expands before the SessionStart hooks finish is UNMEASURED; a typed /janitor-resume that lands before the Jev summary defers the resume to the next heartbeat (delay, not loss). (b) [janitor-renew] path: dispatch.py:3749/:3781, test tests/test_dispatch_cadence.py:162 (unrun). (c) handoff_clear_verify: the SURVIVED evidence (_prior_cron_deleted, 8 tests) is DELETED, because the re-arm CronDelete that fed it no longer happens and the after-phase runs before the first heartbeat fire (n=1: resume typed 29 s after the clear, first heartbeat prompt 310 s after). KNOWN LIMIT: the verifier can no longer detect a cron that died at a clear: an unchanged heartbeat-cron-id.txt (written only by arm_record) now reads SKIP, and the only FAIL branch needs that file to be empty after the clear, which happens only when an arm starts: arm_prepare.py:154-160 takes (unlinks) the id and arm_record.py:57 writes the new one (CORRECTED 16:05; the 15:57 same-line grep missed the CRON_ID_FILE constant). So that FAIL fires only for an arm that started and never recorded between the two snapshots, never for a cron that died. Detecting a dead cron needs a live signal (a later [janitor-heartbeat] prompt, or the daemon's session-liveness guardian), a later increment if wanted. UNRUN TESTS (pre-push checklist): tests/test_clear_trigger.py (edited clear_bootstrap/plan_clear cases), tests/test_reload_shrink_chain.py::test_clear_plan_resumes_only_while_both_reload_plans_still_rearm (new), tests/test_session_start_rearm_guard.py::test_session_start_emits_heartbeat_self_check_on_clear_when_armed (new), tests/test_handoff_clear_verify.py (renamed ..._cron_survived_unchanged_is_skip_not_a_failure; 8 survival tests removed), tests/test_dispatch_phases.py:4187, tests/test_clear_preserves_live_subagent.py:206, tests/test_token_meter_logs_every_turn.py:96-98, tests/test_dispatch_cadence.py:162. Boxes 2, 3 and 5 stay open until that run is green.
