---
trdd-id: NJ22HNC3
title: Global-disarm must silence per-session heartbeats — not just stop the daemon
column: complete
created: 2026-06-30T12:46:34+0200
updated: 2026-06-30T12:55:00+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: HIGH
effort: S
task-type: bugfix
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit]
impacts: []
attempts: 0
implementation-commits: []
---

# Global-disarm must silence per-session heartbeats — not just stop the daemon

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-30

- **Problem (USER-reported, live):** after `/janitor-global-disarm`, "many janitors
  are still running." Root cause CONFIRMED: `/janitor-global-disarm` sets the
  **kill-switch**, which only stops the global **daemon** + blocks
  `ensure_daemon_running()`. The per-session **heartbeat** (`dispatch.py`) does NOT
  check the kill-switch, so Phase 2 still runs all ~45 detectors every 5 min in
  every armed session. Only `global-pause` silences the heartbeat (Phase 0).
- **Fix (two-pronged, defense-in-depth):**
  1. `dispatch.py` Phase 0 ALSO short-circuits on `gs.kill_switch_present()`
     (new `_phase_globally_disarmed()`, mirrors `_phase_global_paused()`). DURABLE,
     one-flag — makes the kill-switch silence heartbeats once the new version is cached.
  2. `global_control_cli.py` `disarm` ALSO raises the global-pause flag (and `arm`
     clears BOTH). IMMEDIATE — the CURRENTLY-cached `dispatch.py` already honors
     global-pause, so disarm silences already-running heartbeats with no rollout wait.
- **DONE (2026-06-30):** dispatch.py `_phase_globally_disarmed()` + Phase-0 gate;
  global_control_cli `disarm` raises both flags / `arm` clears both; tests added to
  `test_dispatch_phases.py` (3) + `test_global_control.py` (2) — **136 passed** in the
  daemon/control set; `janitor-global-disarm` + `janitor-global-arm` SKILL.md updated.
  Committed. **Operational:** global-pause flag set manually this session already
  stopped the live bleed.
- **ROLLOUT NOTE:** the dispatch.py kill-switch gate only reaches a session once its
  cache holds this version — but `disarm` raising the pause flag covers already-cached
  heartbeats immediately (the belt-and-braces reason). Full rollout rides the next
  `publish.py` + the daemon/`claude plugin update` re-caching.
- **Load-bearing facts:** `dispatch.py:764` `main()` Phase 0 currently checks only
  `_phase_global_paused()`/`_phase_paused()`. The daemon already differentiates
  kill-switch (EXIT) vs global-pause (IDLE) — both must silence the heartbeat.
- **Immediate operational state:** global-pause flag was set manually this session
  (stops the live bleed now); kill-switch already set. Both will be managed by the
  disarm/arm change going forward.

## Why

`/janitor-global-disarm` is the user's "stop everything" command, but its kill-switch
was scoped to the daemon only (TRDD-a3fa4d5d split the two flags: pause silences
heartbeats, disarm stops the daemon). The user reasonably expects disarm to be the
SUPERSET — daemon stopped AND heartbeats silent. The gap let ~45 detectors keep
firing per-session after a disarm, burning tokens (the user's central complaint).

## The change

- **`scripts/dispatch.py`** — add `_phase_globally_disarmed()` (checks
  `gs.kill_switch_present()`, logs `skipped: global-disarm (kill-switch) set`,
  returns True). `main()` Phase 0: `if _phase_globally_disarmed() or
  _phase_global_paused() or _phase_paused(): return 0`. Teardown-free silence; the
  cron stays armed; `/janitor-global-arm` lifts it.
- **`scripts/global_control_cli.py`** — `disarm` sets kill-switch + global-pause;
  `arm` clears both; messages updated; `status` says heartbeats silenced when
  disarmed. `pause`/`unpause` unchanged (pause-flag-only, the idle use case).
- **Skill docs** — `janitor-global-disarm` / `janitor-global-arm` SKILL.md reflect
  that disarm now silences every heartbeat and arm resumes them.
- **Tests** — `dispatch.main()` runs NO detector when the kill-switch is set;
  `global_control_cli disarm` sets both flags, `arm` clears both.

## Acceptance

- With the kill-switch set, a `dispatch.main()` fire writes no `last-run-*.ts`
  detector stamps and emits nothing (silent no-op).
- `global_control_cli disarm` → both `kill-switch.flag` and `global-pause.flag`
  present; `arm` → both absent.
- All existing janitor tests still pass.

## Notes and lessons learned
