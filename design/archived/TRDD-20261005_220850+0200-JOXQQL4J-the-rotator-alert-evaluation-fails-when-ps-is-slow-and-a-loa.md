---
trdd-id: JOXQQL4J
title: The rotator alert evaluation fails when ps is slow and a load stall is reported as a stopped rotator
column: complete
status: archived
created: 2026-10-05T22:08:50+0200
updated: 2026-10-10T03:42:18+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:50+0200
---

# The rotator alert evaluation fails when ps is slow and a load stall is reported as a stopped rotator

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed under very high load: the daemon logged 'rotator-alert: evaluation failed: Command ps -eo args= timed out after 10 seconds', one rotator tick took 717 s, and the next heartbeat showed 'the account rotator has stopped ticking - run /janitor-doctor' although the rotator tick a minute later completed but took 18 s against the usual 1 to 3 s. To do: decide what the alert evaluation does when ps is slow (the evaluation is lost exactly when the host is in trouble), and whether a single late tick under load deserves the doctor remedy. Related: TRDD-JY0OBQZ4.

## Approval log

- 2026-10-05T22:08:50+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T04:31:38+0200 — column → dev by main-agent@ai-maestro-janitor. fix is on a worktree branch, not merged yet
- 2026-10-07T05:15:55+0200 — column → testing by main-agent@ai-maestro-janitor. merged on main; waits for a release and a stalled-ps event in the daemon log
2026-10-09 STAYS in testing (board drain, wave 3; fix commits are ancestors of the v3.8.11 tag and the card's tests pass on a re-run by the assessing worker). Field event not yet seen: a stalled ps handled by claude_running(); 0 matches for 'assuming Claude is running' in the daemon log, whose older entries have rotated out. Assessment: reports/board/20261009_232701+0200-wave3-batchF.md.
2026-10-10 DETECT (board drain step iv): grep -h 'assuming Claude is running' ~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/daemon.log.1 ~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/daemon.log — prints one line per stalled-ps tick handled by claude_running() when the awaited event has happened; today it prints 9 lines, 2026-10-07T21:08:46 to 2026-10-09T04:47:53, each 'rotator tick rc=0 stderr: rotator: ps -eo args= timed out after 10s - assuming Claude is running'. The wave-3 stay note's '0 matches' grepped daemon.log only; the older entries had rotated into daemon.log.1. The string exists only in the fix (commit 9377073e, 2026-10-07 04:31, tags v3.8.3 on), so the field event appears OBSERVED and the card may be ready to close on the main session's judgment. String verified at scripts/oauth_rotator/rotator.py:1643.
2026-10-10 04:25 CLOSING RECORD (main session; the card's promise, from its 2026-10-07 line: 'waits for a release and a stalled-ps event in the daemon log'). (1) Fix 9377073e is in tags v3.8.3, v3.8.10 and v3.8.11. (2) Pinning tests re-run by the main session: test_claude_running_assumes_true_when_ps_times_out, test_claude_running_true_for_claude_argv0, test_claude_running_false_for_rotator_own_argv (tests/test_oauth_rotator.py), 3 passed. (3) Field event read by the main session in global-state/daemon.log.1: nine lines from 2026-10-07T21:08:46 to 2026-10-09T04:47:53, each 'rotator tick rc=0 stderr: rotator: ps -eo args= timed out after 10s - assuming Claude is running', so nine stalled ps calls on the TICK path ended in a completed tick where two were lost on 2026-10-05. NARROWER THAN THE TITLE: the alert-evaluation path was not observed handling a stall; its line goes to the daemon's unrotated stderr file (TRDD-OEGPT048), which was not read. What was read: the two daemon logs, which start at 2026-10-07T18:24, hold no 'rotator-alert: evaluation failed' line. The tick-stalled alarm question lives on TRDD-VN2ASDKJ.
- 2026-10-10T03:42:18+0200 — COMPLETE by main-agent@ai-maestro-janitor. fix released in v3.8.3; pinning tests pass; nine handled stalled-ps ticks in daemon.log.1; alert path unobserved, see Approval log.

## STATE

2026-10-07 investigation (reports/board/20261007_042322+0200-rotator-ps-timeout-and-stderr-tail.md, gitignored; facts copied here): the only ps -eo args= call is claude_running() in scripts/oauth_rotator/rotator.py. It has three callers: the tick guard in cmd_tick, the guard in cmd_capture, and the daemon alert evaluation. Measured in about 52 hours of daemon logs: 10 timeouts, 2 in the tick (2026-10-05 14:41:58 and 15:56:37, each losing the whole tick, and the single retry hit the same timeout) and 8 in the alert evaluation (2026-10-05 06:02:40, 06:09:08, 13:25:51, 21:33:28; 2026-10-06 16:00:55, 17:00:10, 21:07:17, 21:21:24). Scope widened to the lost tick.
2026-10-07 DECISION by the main agent (owner ruling 'decide yourself' applies; reversible): on a ps timeout claude_running() prints one stderr line and returns True. Reason: the guard only answers whether there is anything to do; a wrong True costs one idempotent, lock-guarded tick, a raise costs the whole beat exactly when the host is loaded. This is a deliberate exception to the fail-fast rule. In the alert path the flag gates only the no-rotation-target, spare-stale and tick-stalled conditions (rotator_alert.active_conditions, read by the main agent), which are evaluated on every normal beat while Claude runs, so a stalled ps now evaluates them where it used to skip. In cmd_capture the flag is only the same silent no-op guard. The advisor was not consulted: its agent type is absent from the session's agent list after a plugin reload, and no built-in advisor tool exists in this session. STILL OPEN on this card: whether one late tick under load deserves the tick-stalled alarm and the doctor remedy (TICK_STALL_S against measured tick durations). Code is on a worktree branch, not merged yet.
2026-10-07: the fix is merged on main (9377073e, test hardening cc40a249, merge d8281627). Proof by mutation: with the catch replaced by a re-raise the timeout test fails with subprocess.TimeoutExpired. The line above saying the code is not merged is superseded. The daemon's own stderr, where the new line also lands on the alert path, goes to an unrotated file: TRDD-OEGPT048. Not yet in a release. Remaining on this card: whether one late tick under load deserves the tick-stalled alarm.
2026-10-07: the merged part waits for a release; the open question about the tick-stalled alarm moves to its own card (see below).
2026-10-07: the tick-stalled alarm question is now TRDD-VN2ASDKJ (todo).
2026-10-07 — wording corrected per the 2026-10-05 review recorded on TRDD-P9D6QWMU ('ticked normally a minute later' to 'tick a minute later completed but took 18 s against the usual 1 to 3 s'); the correction was not re-measured.

## Acceptance

- [x] 'decide what the alert evaluation does when ps is slow': on a ps timeout claude_running() prints one line and returns True (9377073e, in v3.8.3); test_claude_running_assumes_true_when_ps_times_out passes on a re-run of 2026-10-10.
- [x] 'waits for a release and a stalled-ps event in the daemon log': nine handled stalled-ps ticks in daemon.log.1, 2026-10-07 to 2026-10-09. NARROWED: seen on the tick path only; the alert-evaluation path was not observed handling a stall.
- [x] 'whether a single late tick under load deserves the doctor remedy': not decided here, moved to TRDD-VN2ASDKJ on 2026-10-07.
