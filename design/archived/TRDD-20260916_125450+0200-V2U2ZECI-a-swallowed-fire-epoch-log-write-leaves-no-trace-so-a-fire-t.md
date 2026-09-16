---
trdd-id: V2U2ZECI
title: A swallowed fire-epoch log write leaves no trace, so a fire that ran looks like a fire that never happened
column: complete
created: 2026-09-16T12:54:50+0200
updated: 2026-09-16T22:26:35+0200
current-owner: session
created-by: session
task-type: bugfix
min-approval-requirement: none
assignee: session
mandate: true
mandated-by: none
approved: true
approval-judge: session
approval-datetime: 2026-09-16T12:54:50+0200
implementation-commits: [3775ac7a, ab0a62c0, 6a5199cd]
---

# A swallowed fire-epoch log write leaves no trace, so a fire that ran looks like a fire that never happened

Read the STATE block at the end of this card first (cause unestablished; the fix and test below presuppose one candidate). Observed 2026-09-16 (the cron fire between 12:46:28 and 12:50:12 local): the first cron fire after the local plugin rolled 3.5.4 to 3.5.5 printed [janitor-quiet] but appended no fire epoch line to .janitor/logs/heartbeat-fires.log and no line to dispatch.log; the next five fires logged normally (report reports/board-drain/20260916_125217+0200-silent-355-fires.md). Suspected cause (UNESTABLISHED, see the Approval log for the three candidates and the discriminator): the fire-log append sits in a fail-open try/except that swallows the exception with no stderr line, and the likely trigger was a filesystem race with the concurrent plugin-cache version swap. Fail-open is right (telemetry must never block a fire); silence is not: an unlogged fire is indistinguishable from a stub that never ran, the exact ambiguity _emit_quiet_if_idle exists to remove. Fix: on the swallowed exception write one line to stderr and, if possible, one state.log_line naming the exception type, mirroring TRDD-9EAQS97B's trace for run_subprocess. Acceptance: (1) a test that makes the fire-log path unwritable asserts the fire still completes and stderr carries one line naming the failure; (2) ruff/mypy/pyright clean; (3) no change to the quiet-token contract.

## Acceptance

- [x] (1) tests/test_dispatch_fire_log_unwritable.py pre-creates heartbeat-fires.log as a DIRECTORY; the real main() still completes (rc 0) and stderr carries one line naming IsADirectoryError — fails on the pre-fix code (commit 3775ac7a).
- [x] (2) ruff, mypy and pyright clean at 3775ac7a, ab0a62c0 and 6a5199cd.
- [x] (3) decision-token contract unchanged — proven as byte-equal stdout clean-vs-directory on the self-disarm path (ab0a62c0); the quiet token itself is not producible in-process without a detector sweep, so this is the reachable form of the promise.

## Approval log

- 2026-09-16T12:54:50+0200 — MANDATE issued by session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-16T12:58:00+0200 — review correction: the cause is NOT established. Two candidates fit the three facts (quiet token printed, no fire line, no dispatch.log line): (A) the fire-log append raised inside its fail-open except and main() went on; (B) an early return upstream of the write printed the quiet token and exited. Discriminator already on disk: the detector outcome stamps in .janitor/state — under (A) at least one last-outcome-*.ts would carry a 12:47-12:49 epoch; the five read so far all carry the 12:46:28 fire's epochs, which leans (B). First step of the fix: list every last-outcome-*.ts epoch, then read main() for a non-silent early return ahead of the fire-log write. Fix shape corrected: stderr only (an already-open fd cannot share a path-level failure); a state.log_line in the same except would fail the same way or crash the fire. Test shape corrected: pre-create heartbeat-fires.log as a DIRECTORY so the append raises IsADirectoryError while dispatch.log in the same dir stays writable; assert quiet token, rc 0, one stderr line naming the error, dispatch.log still written.
- 2026-09-16T13:02:00+0200 — second and final correction this session: the outcome-stamp discriminator is unsound (stamps are written only by detectors that actually ran; at 12:47 every detector was inside its cadence, so no new stamp is expected under either branch). The discriminating absence is the keep-going line: dispatch.log logged 'keep-going: suppressed (user active 21s ago)' at 12:46:28 and the session was equally active at 12:47, so a main() that ran past the fire-log write would have logged it again; it did not. That excludes 'fail-open append failed, rest of main() normal'. Remaining candidates: (B) a non-silent early return in main() before the write, or (C) the stub's own fallback printed the quiet token without invoking dispatch at all (the fire landed during the 3.5.4 to 3.5.5 cache swap). First step: read the stub's fallback branches, then main()'s early returns; the fix may belong in the stub, not dispatch. Body reworded to say the cause is unestablished.
- 2026-09-16T22:21:39+0200 — COMPLETE by the session under the 2026-09-03 standing permission. Commits 3775ac7a (stderr line + directory test), ab0a62c0 (guard + decision-token equality test), 6a5199cd (suppress-shaped guards, truncated exception text — this commit also carries the S2RZHXU7 rotate_to change and the archival of N1CPV1QV/LDSCQ0NU/2SKHJ8NR: a commit-boundary slip, disclosed, not rewritten). Acceptance: (1) test present and fails on the old code; (2) ruff/mypy/pyright clean at every commit; (3) demonstrated as decision-token equality clean-vs-directory on the self-disarm path — the quiet token is not producible in-process without a detector sweep, so the body's name is broader than what was proven. Cause unestablished; see STATE.
- 2026-09-16T22:26:35+0200 — COMPLETE by session. diagnosability fix shipped in the tree; cause recorded as unestablished; acceptance 1-3 evidenced.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-16

CLOSED 2026-09-16 — see the Approval log. Discrimination done (reports/board-drain/20260916_215359+0200-V2U2ZECI-discrimination.md): candidate (C) the stub printing the quiet token itself is REFUTED by code (no print path; every success path is execv), the byte-silent early return is REFUTED by the observed token; candidate (A) is the only one with a matching code shape (a bare except: pass around the append in dispatch.py main()), but the 13:02 keep-going objection to (A) stands unresolved and the one-off write failure was not reproducible in five replays — the CAUSE stays UNESTABLISHED. The fix is diagnosability under any candidate: the except now names the exception on stderr (suppress-guarded, so it can never out-fail the fire); the test pre-creates heartbeat-fires.log as a directory and proves the decision-token contract unchanged on the self-disarm path (the quiet path needs a detector sweep and is not reached in-process). Discriminator for next time: a stderr line appears ⇒ (A); a silent fire with no line ⇒ the write never raised and (A) is dead.
