---
trdd-id: ECHOKVZC
title: Fleet wedge-recovery ESC bypasses the user-interrupt cooldown because pane_actuate has no target-session transcript identity
column: todo
created: 2026-09-17T07:08:04+0200
updated: 2026-09-17T07:33:12+0200
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
