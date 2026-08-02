---
trdd-id: DXM75JB2
title: The PostCompact resume push checks the pending flag at fire time, not at type time
column: complete
created: 2026-08-02T13:05:35+0200
updated: 2026-08-02T19:04:04+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
parent-trdd: 8IZ8COQ8
severity: low
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-08-02

**Not started.** Extracted from TRDD-8IZ8COQ8 at the moment that card closed, because it was
the one candidate fix that card did NOT ship and it would otherwise have been archived with it
— a deferred item living only inside a `complete` card is indistinguishable from a dropped one.

**The gap.** `scripts/resume_trigger.py` decides whether to type `/janitor-resume` by checking
for `resume-after-compact.flag` / `rate-limited.flag` **at fire time**, then detaches a child
that sleeps before sending the keystrokes. If a heartbeat cron fire consumes the flag during
that sleep, the keystrokes still land — a `/janitor-resume` typed into a session that already
resumed. That is the user-visible symptom 8IZ8COQ8 was opened for, in its residual form.

**Why it is LOW and was deprioritised, stated honestly so nobody re-inflates it.** The window is
the injection delay (~2 s), not minutes. 8IZ8COQ8's measurement showed the *reported* spam had a
different cause entirely (a session blocked on `ExitPlanMode` read as dead), and that safety
defect is fixed (`d4498ff`). This one is a spam-reduction nicety on a narrow race — real, but
not a correctness or safety issue. Do not let the parent card's severity carry over to it.

### ✅ 2026-08-02T19:04:04+0200 — CLOSED: the type-time guard shipped, all three acceptance boxes checked

- `terminal_trigger`'s child payload grew an OPT-IN `abort_unless_any` key: after its
  sleep, before the first keystroke, the child aborts unless one of the guard files still
  exists. Absent key = byte-for-byte legacy behavior (compact/reload/clear untouched, and a
  test pins that).
- `resume_trigger` passes both pending flags on BOTH channels. The iTerm path's delay
  MOVED out of AppleScript (where no re-check can run) into the same guarded python child
  (`fire_detached_argv`); the tmux/linux paths thread the guard through
  `send_self_command`. The fire-time NOTHING_PENDING early exit is retained.
- Tests: flag-consumed-during-delay → nothing typed; flag-survives → typed (the positive
  twin that proves the guard is live); no-guard-key → legacy. Non-vacuity mutation-verified
  in the closing commit: guard stripped → the race test reds. Trigger cluster 98 green.

**ORIGINAL NEXT ACTION (done):** move the pending-flag check INSIDE the detached child — re-read the flags after
the sleep, immediately before sending, and abort with the existing `NOTHING_PENDING` outcome if
they are gone. The fire-time check stays as a cheap early exit.

**Acceptance:**
- [ ] The child re-checks both flags after its delay and before the first keystroke.
- [ ] A test that clears the flag DURING the delay and asserts nothing is typed. Verify it is
      non-vacuous: with the re-check removed it must go red (a race test that passes either way
      pins nothing — cf. `[[a-regression-test-must-be-verified-to-fail]]`).
- [ ] The fire-time early exit is retained, so the common no-op path still costs no subprocess.

**Do NOT** widen this into the general "typed commands enqueue while a session is mid-turn"
problem. That is the parent's subject and its answer already shipped elsewhere
(TRDD-8DR0X08A F2, the `trailing_enqueues` wedge short-circuit). This card is one race in one
script.
