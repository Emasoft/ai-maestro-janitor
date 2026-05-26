---
trdd-id: be2efa56-bcbd-465e-890b-eab614a4ff31
title: Global janitor daemon — single-instance owner of global-state auto-update tasks (closes issue #7)
status: completed
created: 2026-05-26T04:15:33+0200
updated: 2026-05-26T04:29:39+0200
---

# TRDD-be2efa56 — Global janitor daemon

**Filename:** `design/tasks/TRDD-20260526_041533+0200-be2efa56-global-janitor-daemon.md`
**Tracked in:** this repo

## 1. Origin

User report (memory emergency, 2026-05-26): 11 concurrent `claude plugin
(marketplace) update` processes were spawned by per-session janitors and
piled up to ~2.8 GB RSS, on top of 6 GB+ of holding state, causing severe
memory pressure on the workstation. Verified the same pattern documented
in **GitHub issue #7** ("Per-project PID dedup cannot prevent concurrent
`claude plugin (marketplace) update` pile-up across sessions").

User instruction:

> "the janitor plugin should use a single global central daemon to handle
> the marketplace updates.. not something that it should delegate to the
> single claude code instances or sessions.. i told you to make the
> marketplace update a different thing from the local plugin updates...
> plugins can be handled singulary by the various janitor sessions, but
> the marketplace update must be handled by the global daemon."

## 2. Decisions (user-confirmed via AskUserQuestion)

- **Lifecycle:** lazy-spawn daemon (cross-platform, no OS service config).
  Each per-session heartbeat checks daemon liveness; if dead, spawns it
  detached. flock guarantees singleton on spawn races.
- **Scope:** daemon owns **marketplace-refresh**, **user-plugins-update**,
  and the **auto-update branch of version-update**. Per-session keeps
  `local-plugins-update`, `project-plugins-update`, `plugin-updates`
  (those are genuinely per-project).

## 3. Architecture

### 3.1 Global state directory

`~/.claude/janitor-global-state/` — system-wide, machine-global.
- `daemon.flock` — held exclusive for the daemon's lifetime (singleton).
- `daemon.pid` — current daemon PID (diagnostic).
- `daemon.heartbeat.ts` — daemon's "alive" tick; updated each loop.
- `daemon.log` — daemon's own log (rotated via state.rotate_log_if_big).
- `marketplace-refresh.last-run.ts` — daemon-side last-run cadence stamp.
- `user-plugins-update.last-run.ts` — same.
- `version-update.last-run.ts` — same (auto-update branch).
- `kill-switch.flag` — present → daemon refuses to start / exits.

### 3.2 `scripts/lib/global_state.py` (new shared contract)

- `global_state_dir() -> Path` → `~/.claude/janitor-global-state/`
  (`$XDG_STATE_HOME/janitor/` on Linux when set; macOS/default → `~/.claude/...`).
- `init_global_state()` → mkdir -p.
- `acquire_singleton_flock() -> Optional[int]` → exclusive non-blocking
  flock on `daemon.flock`; returns fd on success, None if already held.
- `daemon_is_alive(max_silence_s=600) -> bool` → reads daemon.pid + checks
  `kill(pid,0)` + heartbeat.ts younger than max_silence_s.
- `spawn_daemon_detached()` → `subprocess.Popen([sys.executable,
  daemon_path], stdin/stdout/stderr=DEVNULL, start_new_session=True)`. Race-
  safe because the daemon itself acquires the singleton flock on startup;
  losers exit immediately.
- `ensure_daemon_running()` → if not alive AND no kill-switch, spawn.

### 3.3 `scripts/daemon.py` (new long-running process)

```
acquire singleton flock → if not, exit 0
write daemon.pid
register SIGTERM/SIGINT handlers → graceful shutdown
loop:
    if kill_switch present → break
    for task in DAEMON_TASKS:  # marketplace-refresh, user-plugins-update, version-update auto-update
        if task.is_due():
            task.run()  # invokes the actual workload
            task.mark_done()
    update daemon.heartbeat.ts
    sleep min(60s, time_until_next_due)
cleanup: remove pid, release flock
```

Each `DaemonTask` owns:
- name, cadence_s, last-run path
- `is_due()` → epoch-now − last-run ≥ cadence_s
- `run()` → invoke the actual workload (capture stdout/stderr to daemon.log)
- `mark_done()` → atomic_write(last-run.ts, str(now))

### 3.4 Detector refactor (per-session)

- `marketplace-refresh.py` → no longer spawns `claude plugin marketplace
  update` itself. Calls `ensure_daemon_running()` and exits silently. If
  the daemon's marketplace-refresh.last-run.ts is older than, say, 6 h
  (stale-daemon signal), emit one informational drift line so the user
  knows the daemon is not making progress.
- `user-plugins-update.py` → same pattern, same staleness guard.
- `version-update.py` → keep the detection branch (read-only: GitHub
  release vs cached/cron version comparisons + the silent self-renew
  nudges). REMOVE the auto-update spawn (the
  `claude plugin marketplace update` + `claude plugin update
  ai-maestro-janitor@... --scope <auto>` calls). The daemon owns that.

### 3.5 `scripts/dispatch.py` integration

At the top of `main()` (after `_phase_paused()` and rate-limit recovery):

```python
from lib.global_state import ensure_daemon_running
ensure_daemon_running()  # cheap when already alive
```

This is the natural lazy-spawn point: every heartbeat fire ensures the
daemon is up before running per-session detectors.

### 3.6 plugin.json knobs

- `daemon_enabled` (bool, default true) — master switch for the daemon.
  When false, ensure_daemon_running() short-circuits.
- `daemon_marketplace_refresh_interval` (number, default 1800 = 30 min) —
  daemon-side cadence (was 300 s per-session; daemon needs less because
  it's the only writer).
- `daemon_user_plugins_update_interval` (number, default 3600 = 1 h).
- `daemon_version_update_interval` (number, default 21600 = 6 h).
- `daemon_idle_shutdown_hours` (number, default 0 = never) — optional
  auto-exit when no work for N hours (skip in v1).

Existing `marketplace_refresh_interval`, `user_plugins_update_interval`,
`auto_update_on_new_release` knobs become **per-session no-ops** but stay
for backward-compat (silent).

## 4. Race / failure modes

- **Two heartbeats spawn concurrently:** both call `spawn_daemon_detached`;
  both new daemons attempt flock; one wins, the other exits. ✓
- **Daemon crashes:** flock released by kernel on process death; pid file
  becomes stale. Next heartbeat sees `kill -0 fails` → spawns new daemon. ✓
- **Daemon hangs (no progress):** heartbeat-ts goes stale; sessions still
  see "alive" (pid OK) but stop trusting it. Sessions emit a
  "daemon stuck" drift line on stale heartbeat-ts; user kills the daemon
  manually (`kill <daemon.pid>` then next heartbeat respawns).
- **Stale PID after reboot:** PID file might collide with an unrelated
  process post-reboot. `daemon_is_alive` also checks the comm/exe path
  of the PID matches `daemon.py` (defensive); otherwise treats as dead.

## 5. Compatibility / upgrade

- Existing armed janitors with the old 0.5.0 detectors keep working (they
  just do nothing global; the user has chmod -x'd them per the emergency
  patch).
- On install of v0.5.2+ (with the daemon), the chmod -x of 0.5.0 detectors
  becomes irrelevant — the new version replaces them with the no-op
  refactored versions.
- v0.5.1 publish (CPV #40 blocked) is unrelated; daemon ships in v0.5.2
  or v0.6.0.

## 6. Tests

- `test_global_state.py`: dir creation; flock singleton (try parallel
  acquire); daemon_is_alive truth table (no pid / dead pid / stale
  heartbeat / live + recent).
- `test_daemon.py`: spawn → run a single fast fake task → mark_done →
  loop → SIGTERM → graceful cleanup; race two concurrent spawns → only
  one acquires flock; kill-switch.flag → daemon exits.
- `test_marketplace_refresh_refactor.py`: detector exits 0 silently; calls
  `ensure_daemon_running()` (verify by intercepting via a stubbed daemon
  binary on PATH); when daemon last-run is stale, surfaces drift.
- Same for `test_user_plugins_update_refactor.py`.
- `test_version_update_refactor.py`: detection branch still fires; auto-
  update branch no longer spawns `claude plugin update`.

## 7. Implementation order

1. `scripts/lib/global_state.py` + tests.
2. `scripts/daemon.py` + tests.
3. Refactor `marketplace-refresh.py` + test.
4. Refactor `user-plugins-update.py` + test.
5. Refactor `version-update.py` (extract auto-update branch) + test.
6. `dispatch.py` integration.
7. plugin.json + README.
8. Final lint + pyright + full suite + commit.

## 8. Out of scope (deferred)

- launchd/systemd service install (Option 3 of the lifecycle question).
  Lazy-spawn covers all platforms.
- Idle shutdown (knob exists, default 0 = never).
- Auto-uninstall of orphaned pre-daemon detectors in the cache (the user
  applied chmod -x manually; a future installer can be more elegant).
- Cross-project local-/project-plugins-update coordination (those stay
  per-session per user decision).

## 9. Status updates (in-session)

- 2026-05-26T04:15:33+0200 — TRDD authored. Implementation starts now.
- 2026-05-26T04:29:39+0200 — v1 landed. Scope shipped: `scripts/lib/global_state.py`,
  `scripts/daemon.py`, refactored `marketplace-refresh.py` + `user-plugins-update.py`
  as thin shims, `dispatch.py` calls `ensure_daemon_running()` after the pause/
  rate-limit phases, 14 new global_state tests + 6 daemon subprocess tests
  (gh-stubbed; isolated tmp state dir), plugin.json knobs (`daemon_enabled`,
  `daemon_marketplace_refresh_interval`, `daemon_user_plugins_update_interval`),
  `auto_update_on_new_release` default flipped to `false` until version-update's
  auto-update branch moves to the daemon. README documents the daemon, the
  state-file table, and manual controls (kill switch, kill, log inspection).
  Full suite: 154 passed; pyright scripts/: 0 errors; ruff: clean.
  **Deferred** to a follow-up TRDD: moving `version-update.py`'s auto-update
  branch into the daemon (the detection branch keeps surfacing manual-update
  nudges; auto_update_on_new_release defaults off so no pile-up risk).
