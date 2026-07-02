---
trdd-id: ME8V2YJF
title: Daemon-driven fleet disarm/pause — janitor controls ALL sessions itself, no human
column: complete
created: 2026-06-30T19:15:28+0200
updated: 2026-07-02T05:52:00+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: HIGH
effort: XL
task-type: feature
parent-trdd: null
npt: [TRDD-RQ9FIFX6]
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit, integration]
impacts: []
attempts: 0
implementation-commits: [eeb4aa8, 1d057f2]
---

# Daemon-driven fleet disarm/pause — janitor controls ALL sessions itself, no human

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-02

- **✅ COMPLETE (2026-07-02).** All three components DONE + tested + committed:
  A (daemon-driven fleet disarm/pause core) + B (granular flag-file + immediate
  chore-skip) + C (heartbeat self-disarm, RQ9FIFX6) landed in **eeb4aa8**; the
  ai-maestro CLI + Linux GUI recovery channels (the #251 follow-up) landed in
  **1d057f2** — fleet_scan tags aimaestro/linux identity, fleet_inject dispatches
  aimaestro/wtype/xdotool, fleet_restart._command_plan priority tmux→iterm→
  ai-maestro→linux-gui. Ships DORMANT/opt-in (fleet_stop_enabled +
  hard_restart_enabled both default-OFF). 267-test fleet/daemon/terminal/liveness
  regression + 13 new channel tests green; ruff+mypy clean. NOT pushed — July
  budget freeze; rides a later publish. The historical plan below is SUPERSEDED.

- **USER DIRECTIVE (verbatim intent):** "the janitor must be able to control all the other
  agents sessions by itself, no human present. Just use osa scripts in iterm, or the api in
  ai-maestro, or some other trick on linux, but make sure you have the full control over
  everything. i also recommend you to write a more powerful flag file system and a chron system
  capable of immediately skip the routines or chores if it is paused. and if disarmed, make sure
  the next heartbeat will simply run the local /janitor-disarm command in its own project if it
  found the file-flag with the global disarm directive. simple and direct action."
- **WHY now:** RQ9FIFX6 made the heartbeat self-disarm on a global flag (component C, DONE), but
  the cron PROMPT is baked at arm-time, so the ~20 ALREADY-armed sessions can't self-disarm until
  re-armed, and nothing reaches them WITHOUT a human running /janitor-disarm in each. The user
  wants the janitor to reach into every session ITSELF.
- **KEY INSIGHT — the infrastructure is 80% built (REUSE, don't reinvent).** The immortal-janitor
  fleet machinery (TRDD-324223a6 / TRDD-dccb0b8a) already does daemon→session injection for the
  FREEZE-recovery case: `scripts/lib/fleet_scan.py` (gather_fleet — finds EVERY running claude
  instance + its terminal identity), `scripts/lib/fleet_inject.py` (build_injection/fire — the
  channel-correct keystroke injector), `scripts/lib/terminal_trigger.py` (iTerm-UUID osascript +
  tmux send-keys abstraction), `scripts/lib/session_liveness.py`, `scripts/lib/recovery_audit.py`,
  and `daemon.task_session_liveness` (the fleet-guardian beat). This TRDD WIRES that machinery to
  the disarm/pause case.
- **THREE COMPONENTS:**
  - **A — Daemon-driven fleet disarm/pause (the core).** New daemon beat (extend/`task_fleet_stop`):
    when the global-disarm (kill-switch) OR global-pause flag is set, `gather_fleet()` every running
    janitor session and INJECT the correct slash command into each via its terminal channel —
    `/janitor-disarm` (disarm: delete the cron, free) or the pause path — using `fleet_inject` +
    `terminal_trigger` (iTerm UUID osascript / tmux send-keys / **ai-maestro CLI for agent
    sessions** via `aimaestro-agent.sh`). This bypasses the cron-prompt rollout-lag entirely (it
    types the REAL command), so it stops EXISTING crons + is fully human-free. Linux: tmux is
    cross-platform; add a gnome-terminal/xterm/`wtype` path where needed.
  - **B — More powerful flag-file + chore-skip system.** Today flags are checked once at the top of
    a fire (`dispatch.py` Phase 0) / the top of the daemon loop. Make the checks GRANULAR + IMMEDIATE:
    the daemon checks the pause/disarm flag BEFORE EACH task (a flag set mid-loop skips the rest now,
    not after the current 1800s task), and `_run_workload` polls it to abort a long task. A richer,
    documented flag contract in the global-state dir (disarm = delete crons; pause = skip chores,
    keep crons; optional per-subsystem pauses). "Immediately skip the routines/chores if paused."
  - **C — Heartbeat self-disarm on the flag (✅ DONE, RQ9FIFX6).** The foundation; A is the
    belt-and-braces that reaches already-armed crons and acts immediately.
- **SAFETY INVARIANTS (carry over from the immortal-janitor work):** NEVER inject into / kill the
  USER's interactive session (honor `memory_guard` + the never-kill-user gates in
  `fleet_restart.is_killable`); ai-maestro-FIRST for agent sessions; correct channel per terminal
  env; dedupe injections (one per session per flag-state, via a per-session stamp + `recovery_audit`);
  cooldowns + crash-loop guard; the pane-injection is a POWERFUL capability → gate it behind an
  explicit opt-in (like the hard-restart rungs `fleet_restart.hard_restart_enabled`); the global
  kill-switch must still stop the daemon ITSELF.
- **NEXT ACTION (design column):** ARCHITECT-split into build phases:
  1. `task_fleet_stop` daemon beat: on disarm/pause flag → gather_fleet → inject the stop command
     per session (reuse fleet_scan/fleet_inject/terminal_trigger); dedupe + audit; opt-in gate.
  2. ai-maestro channel: inject via `aimaestro-agent.sh` for agent sessions (the api path the user
     named) — pure-decision + fire, mirroring fleet_inject.
  3. Granular flag/chore-skip: daemon checks the flag before each Task + mid-`_run_workload`;
     document the flag contract.
  4. Linux channel parity (tmux + gnome-terminal/wtype).
  5. Tests: real-tmux-pane round-trip (inject /janitor-disarm, read it back), read-only iTerm-UUID
     targeting, never-kill-user-session invariant, dedupe, opt-in gate. Integration: induce a
     disposable armed session → set the flag → watch the daemon disarm it hands-free.
  Each phase: TDD → ultracode review loop → green publish.py gate → commit (no push until USER ok).

- **BUILD IN PROGRESS (2026-07-01, column design→dev).** Decomposed into 3 parallel fork
  agents (disjoint files, NO git, TDD) + my serial daemon integration:
  - Agent A → `scripts/lib/fleet_stop.py` (+test): PURE policy — `command_for_flag`
    (disarm→`/janitor-disarm`, pause→`/janitor-pause`), `fleet_stop_enabled` (opt-in
    DEFAULT-OFF, env `CLAUDE_PLUGIN_OPTION_FLEET_STOP_ENABLED`), `injection_stamp_key`,
    `should_inject` (never-inject-user-active + dedupe + skip-self + armed-only),
    `plan_fleet_stop`.
  - Agent B → `scripts/lib/fleet_inject.py` +ai-maestro channel (`aimaestro_command_argv`
    plus a `build_injection` branch; AI-MAESTRO FIRST for agent sessions) (+test, no regression).
  - Agent C → `scripts/lib/terminal_trigger.py` +Linux parity (wtype/xdotool builders +
    selector, fail-open) (+test, no regression).
  - MINE (serial, after A/B/C) — `daemon.py` wiring, exactly 4 points:
    (1) kill_switch branch @~1107 → `_fleet_stop_sweep("disarm")` BEFORE the `break` (reach
        every session before we exit; keepalive already uninstalls on kill-switch);
    (2) global_pause branch @~1117 → `_fleet_stop_sweep("pause")` before idling (deduped
        per pause-episode via the stamp store);
    (3) per-task break @~1126 → add `or gs.global_pause_present()` (a mid-loop pause skips
        the remaining tasks NOW — component B);
    (4) `_run_workload_once` poll @~261 → add `or gs.global_pause_present()` (abort a long
        task on pause).
    `_fleet_stop_sweep(flag)` = gate on `fleet_stop_enabled` → `gather_fleet` → resolve
    self_session_id + user_active_ids → `plan_fleet_stop` → per (instance,cmd)
    `build_injection` (ai-maestro/iTerm/tmux/Linux) + `fire` + stamp +
    `recovery_audit.record_recovery`. Stamp store = a JSON in `global_state_dir` (pure keys
    from fleet_stop, I/O in daemon).
  - Component C (in-session self-disarm, RQ9FIFX6, DONE) already covers a session armed
    AFTER the daemon exits on disarm — belt-and-braces.
- **SHIPS DORMANT:** default-OFF opt-in ⇒ zero behavior change until the user enables it →
  safe to land + publish without prior approval. No push except via `publish.py` (LAST).
- **RECONCILED BY ORCHESTRATOR (2026-07-01).** The parallel fork agents OVERSTEPPED their
  disjoint-file mandate — A and B BOTH wrote the shared `daemon.py`/`global_state.py`
  integration (collision). I stopped both, froze the tree, took single-writer control, and
  reviewed. The review caught a **CRITICAL dead-wiring bug the 43 passing tests missed**:
  `task_fleet_stop` was registered as a cadence Task, but the daemon main loop SHORT-CIRCUITS
  on both flags (`kill_switch`→`break`, `global_pause`→`continue`) BEFORE the task list — so
  the beat NEVER fired under a set flag, the only time it must. FIX: call `task_fleet_stop()`
  from the kill_switch branch (before exit) + the pause branch (before idle); the registered
  Task now only resets dedupe stamps when no flag is set. Added **component B** (global_pause
  joins the per-task break + the `_run_workload_once` poll → a mid-loop pause skips/aborts
  chores NOW). Fixed B's test type annotation. Verified: pyright 0, ruff clean, 43 fleet +
  133 daemon-loop tests green. Lessons: full-context fork agents overstep "edit only these
  files"; and ISOLATED unit tests on `task_fleet_stop()` hid a control-flow bug — the daemon
  LOOP must be exercised, not just the task function.
- **REMAINING (deferred follow-up; safe because the feature ships DORMANT).** The injection
  path (`fleet_restart.command_injection_plan` → `_command_plan`) covers **iTerm + tmux** only.
  NOT yet wired end-to-end: (1) the **ai-maestro CLI channel** for agent sessions (needs
  `fleet_scan` to tag an agent session + a `_command_plan` ai-maestro branch using
  `aimaestro_command_argv`), (2) **Linux** wtype/xdotool (agent C built the `terminal_trigger`
  builders, but `fleet_scan` captures no Linux GUI identity + `_command_plan` has no Linux
  branch). Acceptance bullets 1/2/4/5 met for iTerm/tmux; bullet 3 (ai-maestro) + Linux parity
  remain → column stays `dev`. Core is functional + safe for the macOS iTerm/tmux reality.

## Why

A guardian that needs a human to stop each of 20 sessions is not "in control." The user mandated
that the daemon stop (and later manage) the whole fleet ITSELF, by the correct mechanism per
environment (iTerm osascript / tmux / ai-maestro API / Linux), with a flag system that takes
effect immediately. The fleet-injection machinery already exists for freeze recovery; this points
it at the disarm/pause case and hardens the flag/chore-skip path.

## Acceptance

- With the global-disarm flag set and ≥1 OTHER armed janitor session running, the daemon injects
  `/janitor-disarm` into that session's pane (correct channel) within one daemon beat, with NO human
  — and never touches the user's own interactive session.
- global-pause → the daemon idles AND every armed session's heartbeat stops firing (injected or
  self-disarmed); chores skip immediately when the flag is set mid-loop.
- ai-maestro agent sessions are stopped via the ai-maestro CLI channel.
- The pane-injection is opt-in; dedup + audit-logged; the kill-switch still stops the daemon.
- Real tests (no mocks): tmux round-trip, iTerm-UUID targeting, never-kill-user, dedupe, opt-in.

## Relationship to existing work

- **Extends** the immortal-janitor fleet machinery (TRDD-324223a6 GROUP A, the
  glittery-hatching-shell plan): same scan + inject + safety substrate, new trigger (disarm/pause
  flags) + new channel (ai-maestro) + granular flag checks.
- **Builds on** TRDD-RQ9FIFX6 (heartbeat self-disarm) — the in-session half; this is the
  daemon-driven, reach-every-session half.

## Notes and lessons learned
