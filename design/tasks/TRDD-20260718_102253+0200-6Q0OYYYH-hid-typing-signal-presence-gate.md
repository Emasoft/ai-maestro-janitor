---
trdd-id: 6Q0OYYYH
title: Real typing signal for the presence gate — HID idle probe gates EVERY injection surface
column: dev
created: 2026-07-18T10:22:53+0200
updated: 2026-07-18T10:22:53+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
related-trdd: [P7WU40G9, WBYFTU2L, 0GPQROC1, ME8V2YJF]
implementation-commits: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-18

**INCIDENT (owner, 2026-07-18, verbatim): "why everything is still injecting commands as I
type? didn't i tell you to change the user-presence reporting to make sure the user is
detected as present if it was typing in the last 20 seconds?"**

ROOT CAUSE: presence was SUBMIT-based — `state.bump_user_presence` stamps only when a prompt
is SUBMITTED (UserPromptSubmit hook), never per keystroke. A user mid-typing whose last Enter
was older than the window read as ABSENT. The 2026-07-17 window shrink (300s→10s) made this
WORSE: the moment 10 s passed after the last submit, every gate licensed injection — even
mid-sentence.

**THE FIX — a REAL typing signal:** `user_intent.hid_idle_seconds()` reads macOS
IOHIDSystem's `HIDIdleTime` (ns since the last keyboard/mouse event, machine-wide, no
permissions; min across matches; fail-open None on non-mac/error). Verified live: probe read
10.9 s exactly when the owner had typed 11 s earlier.

Wired as **RUNG 0 of every injection gate** (any HID event within `USER_PRESENT_IDLE_S`,
now **20 s** per the directive ⇒ PRESENT, machine-wide — a human at the keyboard must never
have commands typed under them regardless of target pane):
1. `user_intent.user_is_present` — covers `injection_allowed` → `terminal_trigger.
   send_self_command` (compact/reload/resume/skills self-triggers), dispatch, the
   proactive-compact hook. Breadcrumb rungs unchanged as fallback (probe None).
2. `post-compact-resume.py::_user_recently_active` — the resume-push grace (default 10s→20s).
3. `daemon.py` recovery beat — defers ALL gentle/hard recovery injections for the beat while
   typing (re-runs ~2 min; a frozen session recovers the moment the human steps away).
4. `daemon.py` fleet-stop beat — while typing, every pid counts user-active (the flag is
   held; the next beat delivers).

Machine-wide vs per-pane (2026-07-16 directive) is NOT a conflict: that directive killed a
30-MINUTE global submit window that blocked self-triggers everywhere; this is a 20-SECOND
window on REAL keystrokes — it blocks only while the human is literally typing right now.

## Verification
- Live probe: hid_idle_seconds() tracks real typing (verified 10.9s/11s).
- Unit: user_is_present returns True when the HID probe reports ≤ window regardless of
  breadcrumbs; falls back to breadcrumb rungs when the probe is None (monkeypatched).
- Regression: existing user_intent/presence/fleet suites stay green.

**NEXT ACTION:** tests + ruff + full-suite publish (v0.56.0).

## Notes and lessons learned

[^1]: [id:ATOM-HID-TYPING, status:valid, keywords:"commands injected as I type presence submit based not per keystroke HIDIdleTime ioreg typing signal window shrink made worse", ocd:2026-07-18, lmd:2026-07-18]
  DO NOT gate keystroke injection on a SUBMIT-stamped presence breadcrumb, BECAUSE a user
  mid-typing has no recent submit and reads as absent — and SHRINKING the window makes the
  hole bigger, not smaller. DO gate on a real input signal (macOS IOHIDSystem HIDIdleTime —
  moves on every keystroke/mouse event) and keep the breadcrumb only as the no-probe fallback.
