---
trdd-id: FPL60EKV
title: Maintenance-mode — keep the cache warm cheap instead of disarming (one session must not un-gate the fleet)
column: published
created: 2026-07-02T01:56:08+0200
updated: 2026-07-02T03:47:49+0200
current-owner: autonomous-go-on-yourself
assignee: autonomous-go-on-yourself
priority: 2
severity: MEDIUM
effort: S
labels: [heartbeat, fleet-control, budget, self-disarm]
task-type: feature
parent-trdd: null
npt: []
eht: []
blocked-by: []
supersedes: []
superseded-by: []
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
merge-strategy: squash
must-pass-tests-before-merge: true
publish-target: ai-maestro-plugins
publish-channel: stable
test-requirements: [unit, lint]
audit-requirements: []
review-requirements: []
runtime-targets: [macos, linux]
impacts: []
attempts: 1
test-failures: 0
last-test-result: pass
implementation-commits: [11458b5]
published-version: 0.27.0
published-at: 2026-07-02T03:47:49+0200
external-refs: [github.com/Emasoft/ai-maestro-janitor/releases/tag/v0.27.0]
---

# TRDD-FPL60EKV — Per-session keepalive override

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-02

- **USER authorization (verbatim intent):** the user re-pasted the two-option
  choice from my report and asked "why you are still not resuming the job?" —
  = pick **option 2: "Fix the gap first — make per-session arm NOT un-gate the
  machine-wide daemon/fleet-recovery, so one session can beat while the fleet
  stays quiet."** This TRDD is that fix. (Follows the July-budget fleet-disarm
  incident where I cleared the GLOBAL kill-switch to keep one heartbeat alive and
  woke ~13 frozen sessions — the burn.)
- **THE GAP (verified in code, 2026-07-02):** `dispatch.py` Phase 0
  (`main()` @ ~818) — when the machine-wide kill-switch (`/janitor-global-disarm`)
  OR global-pause is set, EVERY armed session emits `[janitor-self-disarm]` and
  deletes its own cron. To keep ANY session's heartbeat alive you must CLEAR the
  global kill-switch, and `clear_kill_switch()` un-gates `ensure_daemon_running()`
  (`global_state.py:1051` `if kill_switch_present(): return False`) for EVERY
  session → the daemon respawns → fleet-recovery rearms every frozen session.
  There is NO per-session middle ground: "stop the fleet, keep ONE session alive"
  is impossible.
- **PIVOT (USER directive, 2026-07-02):** the per-session "keep firing FULL chores
  despite disarm" override was the WRONG realization — full chores every fire is the
  cost to eliminate. The USER taught the real cost model: a maintenance fire = 0.1x
  cache-READ (~70k); letting the cache DIE = the next real turn pays a 1.0x REWRITE
  (~700k). That 0.1÷1.0 IS the 10x. So the fix became MAINTENANCE-MODE: keep firing but
  CHEAP (cache-refresh only), the middle mode between FULL and DISARM.
- **THE FIX (SHIPPED in-tree, tested):** a three-way heartbeat mode full|maintenance|stop.
  - `dispatch.py`: `_maintenance_mode_active()` (local `.janitor/state/maintenance-mode`
    OR global flag) + `_resolve_heartbeat_mode()` → main() Phase 0 acts on it. Maintenance =
    the fire refreshes the cache + does NOTHING else (no detectors, no daemon spawn, no
    output). Maintenance WINS over a global stop → a session stays warm while the fleet is
    down (option 2, realized CHEAP not full-chore).
  - `global_state.py`: `maintenance_mode_present/set_maintenance_mode/clear_maintenance_mode`
    (machine-wide `maintenance-mode.flag`, mirrors the kill-switch).
  - `daemon.py`: a MAINTENANCE branch idles the daemon's task workloads WITHOUT fleet-stop
    (sessions keep firing cheap), placed above the pause branch (maintenance wins).
  - `global_control_cli.py`: `maintenance` / `maintenance-off` + status shows MAINTENANCE
    (precedence over disarm/pause, mirroring dispatch).
  - Skill `/janitor-maintenance-mode` (local on/off + `global`).
- **KEY COMPOSITION (why no fleet revival):** existing
  `test_ensure_daemon_running_respects_kill_switch` (test_global_state.py:161) proves the
  daemon never spawns under the kill-switch; maintenance returns at Phase 0 BEFORE even
  reaching the daemon phase → daemon stays down regardless.
- **TESTS (green):** +5 global-state/CLI flag tests, +9 dispatch mode/behavior tests
  (maintenance fires cheap: no marker, no detector, no daemon; maintenance-wins-over-kill-
  switch). Existing disarm/pause tests preserved. ruff clean.
- **NEXT ACTION:** finish docs (CLAUDE.md flag model + README), full suite + mypy, commit.
  Then the USER's remaining re-arm conditions (chores-only-when-necessary audit + 10x proof)
  — maintenance-mode is the vehicle that makes re-arm 10x cheaper. The daemon maintenance
  branch mirrors the (subprocess-untested) pause branch — parity follow-up, not a new gap.
- **I do NOT arm / set maintenance for THIS session** — the USER gates re-arm. The vehicle
  is built; using it stays their call.

## Problem

The single global kill-switch conflates two independent concerns:
1. "stop the expensive machine-wide daemon + fleet-recovery" (what a budget
   emergency actually wants), and
2. "make every armed session's cheap heartbeat self-disarm."

You cannot have (1) without (2), and you cannot undo (2) for one session without
undoing (1) for the whole machine. That is exactly the trap that produced the
July-budget burn: keeping one session's beat required clearing the global switch,
which woke the whole fleet.

## Design

- New per-session flag: `.janitor/state/keepalive-through-global-stop` (opt-in,
  default absent). Read via `state.state_dir()` (same pattern as the `paused`
  sentinel).
- `dispatch._phase_session_keepalive_override() -> bool` — True iff the flag file
  exists.
- Refactor the inline Phase-0 block in `main()` into
  `dispatch._phase0_global_stop() -> bool` (returns True iff main() must
  self-disarm-and-return). It folds in the override: on a global stop, if the
  override is present → log + return False (proceed, no marker); else → print the
  bare `[janitor-self-disarm]` marker + return True (unchanged default).
- Everything downstream is untouched: `ensure_daemon_running()` still gates on the
  kill-switch, so a proceeding override-session does NOT revive the daemon/fleet.
- Setter UX: skill `janitor-solo-heartbeat` (`on` / bare sets the flag, `off`
  clears it), documented to be used with `/janitor-arm` (the session must be armed
  to have a cron to keep alive).

## Acceptance criteria

- `_phase_session_keepalive_override()`: absent→False, present→True.
- `_phase0_global_stop()`: no-stop→False/no-output; kill-switch|pause without
  override→True + bare marker; kill-switch|pause WITH override→False + NO marker.
- Existing `test_main_self_disarms_when_globally_disarmed/paused` still pass
  (default behavior unchanged).
- `ensure_daemon_running` under kill-switch still returns False (existing test,
  composed — no fleet revival even when a session proceeds).
- ruff/mypy clean; full `tests/` suite green.
- Skill + CLAUDE.md skills list + README updated.

## Notes and lessons learned
