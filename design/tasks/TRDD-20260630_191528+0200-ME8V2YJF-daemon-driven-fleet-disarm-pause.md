---
trdd-id: ME8V2YJF
title: Daemon-driven fleet disarm/pause — janitor controls ALL sessions itself, no human
column: design
created: 2026-06-30T19:15:28+0200
updated: 2026-06-30T19:15:28+0200
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
implementation-commits: []
---

# Daemon-driven fleet disarm/pause — janitor controls ALL sessions itself, no human

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-30

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
