---
trdd-id: V2U2ZECI
title: A swallowed fire-epoch log write leaves no trace, so a fire that ran looks like a fire that never happened
column: todo
created: 2026-09-16T12:54:50+0200
updated: 2026-09-16T12:57:34+0200
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
---

# A swallowed fire-epoch log write leaves no trace, so a fire that ran looks like a fire that never happened

Observed 2026-09-16 12:47 local: the first cron fire after the local plugin rolled 3.5.4 to 3.5.5 printed [janitor-quiet] but appended no fire epoch line to .janitor/logs/heartbeat-fires.log and no line to dispatch.log; the next five fires logged normally (report reports/board-drain/20260916_125217+0200-silent-355-fires.md). Suspected cause (UNESTABLISHED, see the Approval log for the three candidates and the discriminator): the fire-log append sits in a fail-open try/except that swallows the exception with no stderr line, and the likely trigger was a filesystem race with the concurrent plugin-cache version swap. Fail-open is right (telemetry must never block a fire); silence is not: an unlogged fire is indistinguishable from a stub that never ran, the exact ambiguity _emit_quiet_if_idle exists to remove. Fix: on the swallowed exception write one line to stderr and, if possible, one state.log_line naming the exception type, mirroring TRDD-9EAQS97B's trace for run_subprocess. Acceptance: (1) a test that makes the fire-log path unwritable asserts the fire still completes and stderr carries one line naming the failure; (2) ruff/mypy/pyright clean; (3) no change to the quiet-token contract.

## Approval log

- 2026-09-16T12:54:50+0200 — MANDATE issued by session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-16T12:58:00+0200 — review correction: the cause is NOT established. Two candidates fit the three facts (quiet token printed, no fire line, no dispatch.log line): (A) the fire-log append raised inside its fail-open except and main() went on; (B) an early return upstream of the write printed the quiet token and exited. Discriminator already on disk: the detector outcome stamps in .janitor/state — under (A) at least one last-outcome-*.ts would carry a 12:47-12:49 epoch; the five read so far all carry the 12:46:28 fire's epochs, which leans (B). First step of the fix: list every last-outcome-*.ts epoch, then read main() for a non-silent early return ahead of the fire-log write. Fix shape corrected: stderr only (an already-open fd cannot share a path-level failure); a state.log_line in the same except would fail the same way or crash the fire. Test shape corrected: pre-create heartbeat-fires.log as a DIRECTORY so the append raises IsADirectoryError while dispatch.log in the same dir stays writable; assert quiet token, rc 0, one stderr line naming the error, dispatch.log still written.
- 2026-09-16T13:02:00+0200 — second and final correction this session: the outcome-stamp discriminator is unsound (stamps are written only by detectors that actually ran; at 12:47 every detector was inside its cadence, so no new stamp is expected under either branch). The discriminating absence is the keep-going line: dispatch.log logged 'keep-going: suppressed (user active 21s ago)' at 12:46:28 and the session was equally active at 12:47, so a main() that ran past the fire-log write would have logged it again; it did not. That excludes 'fail-open append failed, rest of main() normal'. Remaining candidates: (B) a non-silent early return in main() before the write, or (C) the stub's own fallback printed the quiet token without invoking dispatch at all (the fire landed during the 3.5.4 to 3.5.5 cache swap). First step: read the stub's fallback branches, then main()'s early returns; the fix may belong in the stub, not dispatch. Body reworded to say the cause is unestablished.
