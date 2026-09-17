---
trdd-id: ECHOKVZC
title: Fleet wedge-recovery ESC bypasses the user-interrupt cooldown because pane_actuate has no target-session transcript identity
column: testing
created: 2026-09-17T07:08:04+0200
updated: 2026-09-17T18:52:11+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: feature
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-17T07:08:04+0200
priority: high
---

# Fleet wedge-recovery ESC bypasses the user-interrupt cooldown because pane_actuate has no target-session transcript identity

Symptom: fleet_inject.py:513-588 (fleet_inject.fire, the daemon's wedge-recovery ESC sender used by pane_actuate.py:95-119 act()/build_step_plan()) never calls terminal_trigger's interrupt-cooldown gate (_interrupt_cooldown_age/recently_interrupted) at all -- it sends the iterm channel via a bare subprocess.Popen(osascript) and the tmux/wtype/xdotool channels via terminal_trigger._fire_detached_steps, the raw low-level runner with no cooldown check. The only human-safety gate on this path is pane_actuate.presence_blocked_now() (pane_actuate.py:68-77), which checks live HID idle time, not whether the user just hit Esc and stepped away -- exactly the gap TRDD-6P0KUSO9/PA9E2GJ1 targeted for other injectors. session_liveness.py has no sender of its own (detection only: is_retry_wedge, diagnose_instance, etc feed pane_actuate's decision, they never send a keystroke) -- same site as the fix.

Why no mechanical fix today: the 300s cooldown gate (user_intent.recently_interrupted) needs a transcript_path naming the TARGET session's own transcript. pane_actuate acts on OTHER agents' fleet panes (a different project, possibly a different machine's session); neither pane_state nor fleet_scan's captured terminal identity (tmux_pane/iterm_session_id/project_dir) carries that target's own transcript path. The cheap guess ("newest transcript under that project's slug") is precisely the fallback recently_interrupted's own docstring forbids -- reusing it here reintroduces the "two sessions share a cooldown" bug class PA9E2GJ1 just fixed elsewhere.

Design needed: carry the target instance's transcript path in the pane registry / fleet_scan record (populated when the daemon first discovers/attaches the pane), or have the target's own hooks stamp a last-interrupt-timestamp file the actuator can read directly without needing the transcript at all.

Acceptance: a test where the target session was interrupted 60s ago receives no ESC from a fleet wedge-recovery send; a test where it was interrupted 400s ago does receive it.

Origin: TRDD-PA9E2GJ1 follow-up 2026-09-17 (reports/board-drain/20260917_impl-PA9E2GJ1-followup.md, candidates 4-5). Parent: TRDD-N954KWUC's reader/policy/actuator split.

## Approval log

- 2026-09-17T07:08:04+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-17T07:33:12+0200 — column → todo by worker-board-drain. PA9E2GJ1's cooldown-bypass candidate — not a deferral by design, moves off backburner into the drain
- 2026-09-17T08:44:13+0200 — Acceptance reworded to the outcome (ESC withheld inside the target's cooldown), mechanism left to the implementer. Puller: the next board drain — no session is currently assigned; the card waits in todo.
- 2026-09-17T18:43:26+0200 — dev → testing: scripts/lib/user_intent.py (record_pane_transcript, pane_transcript_path, _pane_key, heartbeat-marker skip), scripts/lib/pane_actuate.py (act's cooldown gate, keyed on Event.STOP_FLAG not fail_open), scripts/hooks/on-prompt-submit-user-mem.py + scripts/hooks/on-stop-token-meter.py (publish sites); 8 new tests in tests/test_pane_actuate.py + 8 new tests in tests/test_user_intent_interrupt.py, all real fixtures/tmp files, no mocks of the gate; ruff/mypy/pyright all 0 findings, tldr impact act confirmed no positional-arg caller shift. Review findings applied: event-keyed (not fail_open-keyed) STOP_FLAG exemption, iTerm prefix round-trip test, heartbeat-marker root-cause fix in recently_interrupted with 2 tests, ceilings documented at the act() site. (janitor-main-session via lean-worker)
- 2026-09-17T18:45:41+0200 — adversarial review (fork): main finding accepted and documented (not code-fixed) — a pane-id reused by a NEW session before its first-prompt hook overwrites the mapping can inherit the OLD session's still-on-disk transcript, wrongly deferring one keystroke; failure direction is an extra deferral, never an extra injection, and closing it needs a session identity in the mapping, which the TRDD's own chosen design rules out as new stamp semantics — documented as ceiling 2(b) at the pane_actuate.act gate site. Other findings (unconditional per-prompt write cost, test_a_missing_pane_transcript_mapping_fails_open's narrow scope) reviewed and accepted as already-covered/by-design, no code change. (janitor-main-session via lean-worker)
- 2026-09-17T18:49:59+0200 — coordinator second review: fixed a real defect (act() omitted state_dir=, so recently_interrupted globbed the CALLING process's self-send stamps instead of the TARGET project's, missing a self-sent /janitor-resume echo); added user_intent.target_state_dir(project_dir) shared by pane_transcript_path and act(), a regression test proven to fail without the fix (ESC fired twice) and pass with it. Also replaced bare except/pass with state.log_line (stderr fallback) in both hook wrappers. 96 tests pass, ruff/mypy/pyright clean. (janitor-main-session via lean-worker)
- 2026-09-17T18:51:53+0200 — fixed 3 tree-wide pyright reportOptionalMemberAccess in tests/test_user_intent_interrupt.py (None-narrowing asserts); doc-only extension to target_state_dir on canonicalization parity with state.state_dir(). Whole-tree mypy now shows 1 unrelated error in scripts/lib/terminal_trigger.py:1796 from a concurrent session's TRDD-4JEBTT2C work (not touched, flagged not fixed). All ECHOKVZC-scoped checks green. (janitor-main-session via lean-worker)

## Acceptance

- [ ] the fleet wedge-recovery ESC is withheld for a target session that is inside its own user-interrupt cooldown (however pane_actuate learns which session it is acting on); a test drives an ESC at a freshly-interrupted target session and asserts it is withheld.
