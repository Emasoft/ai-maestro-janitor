#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Global janitor daemon — single-instance owner of machine-global auto-update tasks.

Closes GitHub issue #7. Lazy-spawned by per-session heartbeats via
lib.global_state.ensure_daemon_running(). Singleton guaranteed by exclusive
flock on ~/.claude/janitor-global-state/daemon.flock — when N sessions race
to spawn, only one daemon acquires the lock; the rest exit immediately.

Owns three classes of machine-global work that previously piled up across
sessions (issue #7):
  * marketplace-refresh — `claude plugin marketplace update` (bulk; refreshes
    every configured marketplace globally under ~/.claude/plugins/marketplaces/).
  * user-plugins-update — enumerate user-scope plugins via
    `claude plugin list --json` and run `claude plugin update <id> --scope user`
    on each sequentially.
  * version-update — janitor self-update. Compares the local cache's highest
    installed version against the latest GitHub release of the
    `ai-maestro-janitor` repo declared in plugin.json; when behind, runs
    `claude plugin update ai-maestro-janitor@... --scope <auto>` for every
    settings file that mentions the plugin. On success, sets the
    reload-needed.flag (sibling to TRDD-be2efa56's daemon plumbing) so the
    next heartbeat surfaces [janitor-reload] and Claude routes that to a
    silent /reload-plugins via the cron prompt's silent-execute clause.
    Moved here from `scripts/detectors/version-update.py` per TRDD-be2efa56
    §9 follow-up — the detector now SURFACES drift lines only.

Lifecycle:
  1. Acquire the singleton flock; exit 0 if another daemon is alive.
  2. Write daemon.pid, install SIGTERM/SIGINT graceful-shutdown handlers.
  3. Loop forever:
     a. If kill-switch.flag present → graceful exit.
     b. For each task, if its last-run cadence elapsed → run it (long
        subprocess workloads tick the heartbeat periodically so other
        sessions never see the daemon as stale during legitimate work).
     c. Tick daemon.heartbeat.ts.
     d. Sleep min(60 s, next-task-due) — interruptible by signals.
  4. On exit (signal, kill-switch, fatal error): remove pid, release
     flock (the kernel would do it on death anyway, but tidy is tidy).

Read-only output: nothing on stdout (it's a daemon). All progress goes to
~/.claude/janitor-global-state/daemon.log (rotated by state.rotate_log_if_big).
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import FrameType
from typing import Callable, Optional

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))
sys.path.insert(0, str(_HERE / "oauth_rotator"))

import cache_prune as cp  # noqa: E402  # plugin-cache prune (TRDD-a6d2fdaf, Fix A)
import daemon_path  # noqa: E402  # restore a usable tool PATH under launchd (TRDD-VQ4LX7ND)
import daemon_throttle as dt  # noqa: E402  # low-priority marketplace-refresh (TRDD-TY2EZ8ZH, #244)
import dedupe  # noqa: E402  # emit_once — S6 refused-runaway alert dedupe (TRDD-1T53EKTN)
import disk_pressure as dp  # noqa: E402  # S7 dual disk metric (TRDD-1T53EKTN)
import fleet_inject  # noqa: E402  # A3 terminal-env recovery injector (TRDD-324223a6)
import fleet_recovery as fr  # noqa: E402  # A2 recovery policy (TRDD-324223a6)
import fleet_restart  # noqa: E402  # raw-command channel builder reused by fleet-stop (TRDD-ME8V2YJF)
import fleet_scan  # noqa: E402  # fleet discovery + diagnosis (TRDD-324223a6)
import fleet_stop  # noqa: E402  # daemon-driven disarm/pause policy (TRDD-ME8V2YJF)
import global_state as gs  # noqa: E402
import launchd_keepalive as ka  # noqa: E402  # L0 OS keepalive install/uninstall (TRDD-71ABD7V7)
import memory_guard as mg  # noqa: E402  # Tier-1 OOM guard (TRDD-7100178d Pillar 4)
import recovery_audit as ra  # noqa: E402  # F3 recovery audit log (TRDD-F3AUDLOG) — fail-open side-channel
import rules_installer as ri  # noqa: E402  # post-uninstall orphaned-rule cleanup (TRDD-H9IBY95W)
import session_liveness as sl  # noqa: E402  # diagnosis→recovery mapping (TRDD-324223a6)
import state  # noqa: E402
import supervisor as oauth_supervisor  # noqa: E402  # scripts/oauth_rotator/supervisor.py
import version_update_lib as vu  # noqa: E402

# L0 OS-keepalive (TRDD-71ABD7V7): True iff this process was launched by the OS service
# manager via daemon_keepalive_entry.py (which passes --keepalive). Captured at import time —
# launchd already passes --keepalive as argv[1] and the entry sets argv before main(), so this
# is correct for the OS-spawned daemon and False for a session-spawned one.
_KEEPALIVE_INSTANCE = "--keepalive" in sys.argv


def _env_interval(var: str, default: int) -> int:
    """Cadence knob from userConfig via env. MUST NOT be a bare int(): these run at import
    time with stderr on /dev/null, so one human-shaped value (e.g. "20 min") would kill every
    spawned daemon instantly, trip the crash-loop breaker, and silently stop ALL machine-global
    services (marketplace refresh, plugin updates, OAuth keepalive). coerce_int falls back to
    the default like every other janitor entry point."""
    return state.coerce_int(os.environ.get(var), default)


_INTERVAL_KEEPALIVE_SELF_HEAL = _env_interval(
    "CLAUDE_PLUGIN_OPTION_DAEMON_KEEPALIVE_SELF_HEAL_INTERVAL", 600
)  # 10 min — how often the OS-spawned daemon checks the cache for a newer version to
#  re-stage + exit-for-respawn. Cheap (one dir list + one filecmp); only acts on a real change.

# Default cadences. Each is overridable via the matching env var (the
# per-session userConfig knobs in plugin.json end up here on spawn).
_INTERVAL_MARKETPLACE_REFRESH = _env_interval(
    "CLAUDE_PLUGIN_OPTION_DAEMON_MARKETPLACE_REFRESH_INTERVAL", 1200
)  # 20 min — daemon is the only writer of GLOBAL marketplace refresh
#  (refreshes every configured marketplace in one CLI call). The per-session
#  detector handles narrower local+project marketplaces at 5 min, so the
#  daemon doesn't need to be aggressive here.
_INTERVAL_USER_PLUGINS_UPDATE = _env_interval(
    "CLAUDE_PLUGIN_OPTION_DAEMON_USER_PLUGINS_UPDATE_INTERVAL", 3600
)  # 1 h — full sweep takes ~7 min; hourly cadence keeps everything fresh.
_INTERVAL_VERSION_UPDATE = _env_interval(
    "CLAUDE_PLUGIN_OPTION_DAEMON_VERSION_UPDATE_INTERVAL", 21600
)  # 6 h — janitor self-update cadence. GitHub releases land at human-day
#  granularity; checking every 6 h is plenty and keeps the load light.
_INTERVAL_OAUTH_SUPERVISOR = _env_interval(
    "CLAUDE_PLUGIN_OPTION_DAEMON_OAUTH_SUPERVISOR_INTERVAL", 600
)  # 10 min — the opt-in OAuth-rotator governance/auto-heal task (TRDD-32acd15f
#  P2). A total no-op unless /janitor-auto-manage-oauth-on wrote the opt-in flag,
#  so this cadence is free for every non-opted-in install. When opted-in the
#  steady-state check is cheap (read the opt-in flag, stat the slots); the
#  SessionStart fast-path surfaces alert-only findings the moment a session starts.
_INTERVAL_OAUTH_TICK = _env_interval(
    "CLAUDE_PLUGIN_OPTION_DAEMON_OAUTH_TICK_INTERVAL", 60
)  # 60 s — the opt-in OAuth-rotator beat (TRDD-32acd15f), folded into the daemon
#  per TRDD-f892e109 decision 3: this REPLACES the deleted launchd agent, which ran
#  the same `tick --only-if-claude-running` every 60 s via plist `StartInterval 60`.
#  A total no-op unless the opt-in flag is set AND the real Claude binary is running
#  (the guard lives inside cmd_tick). The daemon loop ceiling is already 60 s, so
#  this is the finest cadence the loop can offer.
_INTERVAL_MEMORY_GUARD = _env_interval(
    "CLAUDE_PLUGIN_OPTION_DAEMON_MEMORY_GUARD_INTERVAL", 120
)  # 2 min — the Tier-1 OOM guard beat (TRDD-7100178d Pillar 4, Decision 1).
#  Steady state is one cheap free-memory read; the ps snapshot + kill logic only
#  runs under real memory pressure, so the cadence costs nothing when healthy.
_INTERVAL_CACHE_PRUNE = _env_interval(
    "CLAUDE_PLUGIN_OPTION_DAEMON_CACHE_PRUNE_INTERVAL", 21600
)  # 6 h — plugin-cache prune (TRDD-a6d2fdaf, Fix A). The cache only bloats over
#  hours/days (a plugin shipping several versions/day), so a 6 h cadence reclaims
#  promptly without churn. The daemon owns it because the cache is machine-global.
_INTERVAL_SESSION_LIVENESS = _env_interval(
    "CLAUDE_PLUGIN_OPTION_DAEMON_SESSION_LIVENESS_INTERVAL", 120
)  # 2 min — the fleet-guardian beat (TRDD-324223a6, A2). A cheap ps + transcript-age
#  scan; an actual recovery only fires for a genuinely frozen / cron-dead /
#  version-mismatched instance and is bounded by a 15 min per-instance cooldown, so
#  the cadence costs ~nothing while the fleet is healthy. This is the immortality the
#  in-session cron cannot provide — it recovers the very heartbeat that died.
_INTERVAL_FLEET_STOP = _env_interval(
    "CLAUDE_PLUGIN_OPTION_DAEMON_FLEET_STOP_INTERVAL", 60
)  # 1 min — the daemon-driven fleet disarm/pause beat (TRDD-ME8V2YJF). A cheap ps +
#  transcript-age scan that no-ops unless a machine-wide disarm/pause flag is set AND
#  the opt-in (CLAUDE_PLUGIN_OPTION_FLEET_STOP_ENABLED=1) is on. A responsive cadence so
#  a global /janitor-global-disarm reaches every already-armed session within ~1 min,
#  with no human — the reach-every-session half of the self-disarm story (RQ9FIFX6).
_INTERVAL_RULES_CLEANUP = _env_interval(
    "CLAUDE_PLUGIN_OPTION_DAEMON_RULES_CLEANUP_INTERVAL", 3600
)  # 1 h — post-uninstall orphaned-rule cleanup (TRDD-H9IBY95W). Steady state is one
#  cheap check (scopes + data-dir stat); it only removes files when the janitor is
#  CONFIRMED fully uninstalled. Hourly is ample: after uninstall the daemon lingers on
#  its orphaned cache for up to ~7 days, so an hourly beat fires many times in that
#  window while the plugin's own hooks can no longer run.

# Loop ceiling — heartbeat tick interval upper bound. Must be << the
# staleness threshold (DEFAULT_DAEMON_STALE_SECONDS = 1800 s) so the heartbeat
# stays well within the alive window when no workload is running.
_LOOP_CEILING_SEC = 60

# Wall-clock cap on a single workload subprocess. Generous: a slow marketplace
# refresh on a flaky network can legitimately take many minutes. Beyond this
# we kill it — a stuck workload would otherwise wedge the daemon forever.
_WORKLOAD_TIMEOUT_SEC = 1800  # 30 min

# How often to tick the heartbeat WHILE a workload is running.
_WORKLOAD_HEARTBEAT_TICK_SEC = 10

# Pillar-1 subprocess retry (TRDD-7100178d Phase 4). A workload that exits
# NON-ZERO (a crash / transient failure) is retried once immediately before
# deferring to the next cadence. A None result (spawn-failure or timeout-kill) is
# NOT retried — a missing binary won't reappear on a retry and a timeout already
# consumed its full budget, so re-running would only double a long wait.
_WORKLOAD_MAX_ATTEMPTS = 2

# Pillar-1 per-task supervision. Task.run already swallows a task exception so one
# crash never kills the daemon, but a PERMANENTLY-broken task must not burn its
# cadence every tick forever. After this many CONSECUTIVE failures the task is
# quarantined: its next-due is pushed out by interval * 2**(fails - K), capped at
# _TASK_MAX_BACKOFF_SEC. A single success resets the streak (see Task.run).
_TASK_BACKOFF_AFTER_FAILS = 3
_TASK_MAX_BACKOFF_SEC = 3600  # 1 h ceiling so a recovered task is retried within the hour

# Patterns that prove a `claude plugin update` subprocess actually changed
# something on disk (vs. "already up to date"). Conservative: any reasonably-
# unambiguous "moved from version X to version Y" phrase. False negatives are
# tolerable (we just wait until the next plugin update to reload); false
# positives would set the reload flag spuriously and surface `[janitor-reload]`
# on no-op fires, which is noisy. The "already" guard short-circuits the
# common "already up to date" line some CLIs emit alongside an "Updated" word.
# `\b` only applies to word-based alternatives — the symbolic arrows are
# non-word chars and a leading `\b` would prevent matches in "v0.4.13 → v0.5.0"
# where the preceding char is a space (also non-word, so no boundary).
_PLUGIN_UPDATED_RX = re.compile(
    r"(?i)(?:\bupdated\s+(?:from|to)\b|→\s*v?\d|->\s*v?\d|\binstalled\s+version\s+\S+)"
)
_PLUGIN_NO_CHANGE_RX = re.compile(r"(?i)\balready\s+(?:up[-\s]?to[-\s]?date|installed)\b")


def _stdout_proves_plugin_updated(stdout: str) -> bool:
    """True iff a `claude plugin update` stdout shows a real version change.

    Designed to be conservative: it's better to miss a reload trigger
    (and wait for the next plugin update) than to fire `[janitor-reload]`
    after a no-op. The match is line-by-line so an "already up to date"
    line elsewhere in stdout doesn't suppress a real "updated to vX" line.
    """
    if not stdout:
        return False
    for ln in stdout.splitlines():
        if _PLUGIN_NO_CHANGE_RX.search(ln):
            continue
        if _PLUGIN_UPDATED_RX.search(ln):
            return True
    return False

_running = True  # flipped to False by SIGTERM/SIGINT — read by the main loop


def _on_signal(signum: int, _frame: Optional[FrameType]) -> None:
    """Graceful shutdown: ask the main loop to exit after current step."""
    global _running
    _running = False
    state.log_line("daemon", f"received signal {signum} — graceful shutdown")


def _run_workload_once(cmd: list[str], *, timeout: int = _WORKLOAD_TIMEOUT_SEC,
                       heartbeat_tick: int = _WORKLOAD_HEARTBEAT_TICK_SEC,
                       preexec_fn: Optional[Callable[[], None]] = None) -> Optional[subprocess.CompletedProcess[str]]:
    """Run a subprocess ONCE to completion, ticking the daemon heartbeat periodically.

    Returns the CompletedProcess on a normal exit (whatever the returncode),
    or None on timeout / spawn failure (already logged). The periodic
    heartbeat tick is what keeps the daemon visible to per-session liveness
    checks during a long `claude plugin marketplace update` (≈10 min).

    This is the single-attempt primitive; `_run_workload` wraps it with the
    Pillar-1 retry-on-non-zero-exit policy.

    `preexec_fn` (optional, TRDD-TY2EZ8ZH): a callable run in the forked child
    just before `exec` — used by `task_marketplace_refresh` to renice the heavy
    refresh to low CPU priority. Defaults to None, so every other caller's
    Popen is byte-identical to before. POSIX-only; harmless where unsupported
    (callers pass None there).
    """
    short = " ".join(cmd[:3]) + ("..." if len(cmd) > 3 else "")
    try:
        proc = subprocess.Popen(  # noqa: S603 - explicit args, no shell
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            close_fds=True,
            preexec_fn=preexec_fn,
        )
    except FileNotFoundError:
        state.log_line("daemon", f"  binary not in PATH: {cmd[0]}")
        return None
    except OSError as exc:
        state.log_line("daemon", f"  spawn failed for `{short}`: {exc}")
        return None

    deadline = time.time() + timeout
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=heartbeat_tick)
            gs.write_heartbeat()
            rc = proc.returncode if proc.returncode is not None else -1
            return subprocess.CompletedProcess(cmd, rc, stdout or "", stderr or "")
        except subprocess.TimeoutExpired:
            gs.write_heartbeat()
            if (
                time.time() > deadline
                or not _running
                or gs.kill_switch_present()
                or gs.global_pause_present()  # component B: abort a long chore on pause
            ):
                state.log_line("daemon", f"  killing `{short}` (timeout or shutdown)")
                proc.kill()
                # communicate() (not wait()) is the documented reap after a
                # communicate() timeout on a PIPE child: it drains the stdout/
                # stderr pipes AND closes their fds deterministically. wait()
                # leaves the read fds open until Popen.__del__ / GC closes them,
                # so under repeated timeouts fd release would depend on GC
                # timing instead of happening here-and-now.
                try:
                    proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                return None


def _run_workload(cmd: list[str], *, timeout: int = _WORKLOAD_TIMEOUT_SEC,
                  heartbeat_tick: int = _WORKLOAD_HEARTBEAT_TICK_SEC,
                  max_attempts: int = _WORKLOAD_MAX_ATTEMPTS,
                  preexec_fn: Optional[Callable[[], None]] = None) -> Optional[subprocess.CompletedProcess[str]]:
    """Run a workload with the Pillar-1 retry policy (TRDD-7100178d Phase 4).

    Calls `_run_workload_once` up to `max_attempts` times, retrying ONLY on a
    non-zero exit (a crash / transient failure). A None result (spawn-failure or
    timeout-kill) and a clean rc==0 both return immediately — a missing binary
    won't reappear on a retry and a timed-out command already spent its budget.
    The retried exit code is logged so a recurring failure is visible. Every
    caller is idempotent (re-running a marketplace refresh / plugin update / usage
    probe has no side effect beyond the intended one), so a single retry is safe.

    `preexec_fn` (optional, TRDD-TY2EZ8ZH) is threaded into every attempt's
    `_run_workload_once`. Default None ⇒ unchanged behavior for every existing
    caller.
    """
    short = " ".join(cmd[:3]) + ("..." if len(cmd) > 3 else "")
    result: Optional[subprocess.CompletedProcess[str]] = None
    for attempt in range(1, max(1, max_attempts) + 1):
        result = _run_workload_once(cmd, timeout=timeout, heartbeat_tick=heartbeat_tick, preexec_fn=preexec_fn)
        if result is None or result.returncode == 0:
            return result
        if attempt < max_attempts:
            state.log_line(
                "daemon",
                f"  `{short}` exited {result.returncode} "
                f"(attempt {attempt}/{max_attempts}) — retrying once",
            )
    return result


# ---------- Tasks --------------------------------------------------------

def task_marketplace_refresh() -> None:
    """Run `claude plugin marketplace update` (bulk → all marketplaces).

    This is the operation that, when fired from N concurrent sessions, was
    the worst contributor to the pile-up reported in issue #7. The daemon
    runs it exactly once per cadence — never overlapping with itself, and
    (via the shared marketplace lock) never overlapping with a per-session
    single-market update either.
    """
    with gs.marketplace_lock() as got:
        if not got:
            state.log_line("daemon", "  marketplace-refresh deferred (another marketplace op holds the lock)")
            return
        # TRDD-TY2EZ8ZH (#244): run this CPU+IO-heavy refresh at LOW priority so it
        # yields to the user's foreground work (it was timing out their Bash/agents/CI).
        # FAIL-OPEN — ANY error building the throttle prefix or the renice preexec
        # falls through to the CURRENT un-throttled invocation. A throttle defect must
        # NEVER break marketplace-refresh or wedge the machine-wide singleton daemon.
        base_cmd = ["claude", "plugin", "marketplace", "update"]
        try:
            prefix = dt._low_priority_prefix()
            preexec = dt.nice_preexec()
        except Exception as exc:  # noqa: BLE001 — throttle is best-effort; never block the refresh
            state.log_line("daemon", f"  marketplace-refresh: throttle skipped ({exc})")
            prefix, preexec = [], None
        if prefix or preexec:
            state.log_line(
                "daemon",
                f"  marketplace-refresh: running at low priority (prefix={prefix or '[]'}, "
                f"nice={'yes' if preexec else 'no'})",
            )
        proc = _run_workload(prefix + base_cmd, preexec_fn=preexec)
        if proc is None:
            return
        if proc.returncode != 0:
            state.log_line("daemon", f"  marketplace-refresh exited rc={proc.returncode}")
            for ln in (proc.stderr or "").splitlines()[:5]:
                state.log_line("daemon", f"    stderr: {ln.strip()}")


def task_user_plugins_update() -> None:
    """Enumerate user-scope plugins and update each sequentially.

    `claude plugin list --json` returns every plugin regardless of scope;
    we filter to scope=="user" in Python (the CLI lacks a `--scope` filter
    flag on `list`). Each entry's `id` is already in `<plugin>@<marketplace>`
    form — exactly what `claude plugin update` accepts.

    Cooperates with shutdown: between every plugin we check the kill-switch
    and the SIGTERM-driven _running flag, so the daemon can drain a long
    sweep in a bounded time when the user wants it to stop.
    """
    listing = _run_workload(["claude", "plugin", "list", "--json"], timeout=60)
    if listing is None or listing.returncode != 0:
        state.log_line("daemon", "  user-plugins-update: `claude plugin list --json` failed")
        return
    try:
        plugins = json.loads(listing.stdout or "[]")
    except json.JSONDecodeError as exc:
        state.log_line("daemon", f"  user-plugins-update: malformed JSON ({exc})")
        return
    if not isinstance(plugins, list):
        return
    all_user = [p for p in plugins
                if isinstance(p, dict) and p.get("scope") == "user" and p.get("id")]
    # R2 (TRDD-db169d9e): NEVER auto-update the ai-maestro fleet. Those plugins'
    # versions are owned by each plugin's own release pipeline; bumping them here
    # causes fleet version skew. The janitor's own id is excluded too — its
    # self-update is the dedicated task_version_update, not this per-plugin sweep.
    user_scope = [p for p in all_user if not state.is_ai_maestro_plugin_id(str(p["id"]))]
    excluded = len(all_user) - len(user_scope)
    total = len(user_scope)
    msg = f"  user-plugins-update: {total} user-scope plugin(s)"
    if excluded:
        msg += f" ({excluded} ai-maestro-plugins member(s) excluded — fleet self-manages)"
    state.log_line("daemon", msg)
    updated_ids: list[str] = []
    for i, p in enumerate(user_scope, start=1):
        if not _running or gs.kill_switch_present():
            state.log_line("daemon", f"  user-plugins-update: aborted at {i-1}/{total}")
            break
        pid = str(p["id"])
        update = _run_workload(
            ["claude", "plugin", "update", pid, "--scope", "user"],
            timeout=120,
        )
        if update is None:
            state.log_line("daemon", f"    ({i}/{total}) {pid} — TIMED OUT / spawn failed")
            continue
        if update.returncode != 0:
            state.log_line("daemon", f"    ({i}/{total}) {pid} — rc={update.returncode}")
            continue
        # Only on rc==0 do we look at stdout for the "actually updated" markers.
        if _stdout_proves_plugin_updated(update.stdout or ""):
            updated_ids.append(pid)
            state.log_line("daemon", f"    ({i}/{total}) {pid} — UPDATED")

    # If any plugin actually changed on disk, request a one-shot
    # `/reload-plugins` so Claude picks up the new hooks/skills without a
    # session restart. The dispatch reload-phase reads + clears the flag.
    if updated_ids:
        gs.set_reload_flag(",".join(updated_ids[:10]))
        state.log_line(
            "daemon",
            f"  user-plugins-update: reload-needed.flag SET ({len(updated_ids)} plugin(s) updated)",
        )


def task_version_update() -> None:
    """Auto-update the janitor plugin itself when GitHub is ahead of the
    local cache. Moved here from `scripts/detectors/version-update.py`
    per TRDD-be2efa56 §9 follow-up — the detector now SURFACES drift
    lines only; the daemon is the single global writer that actually
    runs `claude plugin update`.

    Gated on `CLAUDE_PLUGIN_OPTION_AUTO_UPDATE_ON_NEW_RELEASE`
    (default true; the userConfig knob). When the update succeeds, the
    daemon sets the reload-needed.flag so the next heartbeat surfaces
    `[janitor-reload]` (which Claude silently routes to /reload-plugins
    via the cron-prompt clause).

    The follow-up dispatcher phase 1.65 (`_phase_daemon_restart_if_stale`)
    then SIGTERMs this daemon so the next `ensure_daemon_running()`
    spawns the new daemon from the new cache version. Full auto-roll,
    no human in the loop.
    """
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_AUTO_UPDATE_ON_NEW_RELEASE", True):
        return

    # The daemon lives in `<cache>/<version>/scripts/daemon.py`, so its
    # parent's parent is the version dir we need to pass through.
    plugin_root = Path(__file__).resolve().parent.parent

    def _log(msg: str) -> None:
        state.log_line("daemon", f"  {msg}")

    updated, new_latest = False, ""
    with gs.marketplace_lock() as got:
        if not got:
            _log("version-update deferred (another marketplace op holds the lock)")
            return
        updated, new_latest = vu.do_auto_update_if_needed(
            plugin_root, _log, update_log_path=None,
        )
    if updated:
        gs.set_reload_flag(f"janitor-self-update@{new_latest}")
        state.log_line(
            "daemon",
            f"  version-update: janitor self-updated to {new_latest}; "
            f"reload-needed.flag SET (heartbeat will emit [janitor-reload])",
        )
        # C3 (TRDD-T198DT1W): certify the freshly-installed version as the
        # last-GOOD pin so the dispatcher-stub can cross-check its manifest HMAC
        # on future fires (the malicious-replacement anchor C2's unsigned
        # manifest can't provide). We pin the NEW version's CACHE dir
        # (<cache-parent>/<new_latest>), computing the HMAC over its shipped
        # manifest with the DATA-dir key. Best-effort + FAIL-OPEN: pin_good_version
        # is a no-op when the version shipped no manifest or no key resolves, and
        # any failure just leaves the stub on its C2-only gate — never blocking.
        try:
            new_version_dir = plugin_root.parent / new_latest
            if vu.pin_good_version(new_version_dir, new_latest):
                state.log_line(
                    "daemon",
                    f"  version-update: pinned last-good={new_latest} "
                    f"(C3 manifest-HMAC trust anchor written)",
                )
        except Exception as exc:  # noqa: BLE001 — pinning must NEVER break self-update
            state.log_line("daemon", f"  version-update: last-good pin skipped: {exc}")


def task_oauth_rotator_supervisor() -> None:
    """Governance (alert-only) for the opt-in OAuth account rotator
    (TRDD-32acd15f, P2). The daemon owns this because rotating the live
    credential (a keychain swap) is a user/global-scope mutation (scope
    invariant, issue #7) and the daemon is the always-on singleton —
    "without human, never stopping" by construction.

    A TOTAL no-op unless the opt-in flag is set, so every janitor install
    WITHOUT the rotator pays nothing here. When opted in: gather facts →
    diagnose (pure) → log the alert-only findings (too few captured slots,
    expiring setup-token, pinning env var) for the per-session detector to
    surface to the user. There is no launchd agent to heal any more — the
    60 s `oauth-rotator-tick` task (TRDD-f892e109 decision 3) replaced it.
    """
    facts = oauth_supervisor.gather_facts()
    if not facts.opt_in:
        return  # rotator not activated on this machine -> silent no-op
    findings = oauth_supervisor.diagnose(facts)
    if not findings:
        return

    def _log(msg: str) -> None:
        state.log_line("daemon", f"  {msg}")

    res = oauth_supervisor.apply(findings, log=_log)
    state.log_line(
        "daemon",
        f"  oauth-rotator-supervisor: alerts={res.alerts or '[]'}",
    )


def task_oauth_rotator_tick() -> None:
    """60 s OAuth-rotator beat (TRDD-32acd15f), folded into the daemon per
    TRDD-f892e109 decision 3 — this REPLACES the deleted launchd agent.

    No-op unless the opt-in flag is set; the `--only-if-claude-running` guard
    inside `cmd_tick` makes it a further no-op when the real Claude binary is
    not up. Runs `rotator.py` as a TIMED SUBPROCESS (not in-process) so a hung
    keychain or `/api/oauth/usage` call cannot wedge the daemon main loop —
    `_run_workload` kills it past the timeout. The daemon auto-rolls
    (dispatcher-stub re-execs the latest cached version), so
    `_HERE/oauth_rotator/rotator.py` is always the current rotator and no
    separate auto-roll stub is needed.

    SINGLE-WRITER (audit §3.4): the rotator SUBPROCESS self-locks via
    `gs.oauth_rotator_lock()` inside `rotator.py main()` (skip-if-held), so the
    daemon's tick and a human's manual `rotator.py tick`/`switch`/`migrate-slots`
    contend on the SAME machine-wide flock and can never race state.json + the live
    keychain. The lock lives in the subprocess, NOT here: a daemon-side lock would
    only block the daemon's OWN subprocess (the manual run never checks it), so it
    could not prevent the daemon-vs-manual race. The daemon is already a singleton,
    so there is no daemon-vs-daemon race for a wrapper lock to guard anyway.
    """
    if not oauth_supervisor.opt_in_present():
        return  # rotator not activated on this machine -> silent no-op
    rotator_py = _HERE / "oauth_rotator" / "rotator.py"
    # FIX B2 (TRDD-K3WQ7XM9): mark the rotator subprocess HEADLESS so it NEVER does the
    # prompting `-w` secret read of the ACL-restricted primary live item — a read the daemon
    # can only ever hang/prompt on (the ~100× keychain prompt storm). It resolves the live
    # credential from the -T-accessible -livebak mirror instead (the same resolution it
    # reached after the read failed). The daemon is definitionally headless, so this is always
    # correct here; a manual/session-context `rotator.py tick` never sets it → unchanged.
    os.environ["JANITOR_ROTATOR_HEADLESS"] = "1"
    _run_workload(
        [sys.executable, str(rotator_py), "tick", "--only-if-claude-running"],
        timeout=120,
    )


def task_memory_guard() -> None:
    """Tier-1 OOM guard (TRDD-7100178d Pillar 4, Decision 1 — user-signed 2026-05-31).

    Each beat: read free memory (one cheap syscall-ish probe). Only under real
    pressure does it snapshot the process table TO A FILE (the no-self-match
    discipline; the file is also the forensic record), select the single
    largest-RSS janitor-owned RUNAWAY via the pure Tier-1 truth table
    (signature allowlist + protected pids + claude-session rejection + runaway
    age gate), and SIGTERM->SIGKILL it. At most ONE kill per beat — pressure is
    re-evaluated next beat, so a misread can never cascade.

    Tier 2 (kill the biggest non-interactive process at critical pressure) is
    NOT implemented — per Decision 1 it stays off the table without a fresh
    user sign-off; there is deliberately no code path or enabling flag for it.

    Every kill is logged LOUDLY with the full command line, RSS, age, and the
    free-memory reading that triggered it.
    """
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_MEMORY_GUARD_ENABLED", True):
        return
    min_free_mb = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_MEMORY_GUARD_MIN_FREE_MB"),
        mg.DEFAULT_MIN_FREE_MB,
    )
    free_mb = mg.free_memory_mb()
    if free_mb is None or free_mb >= min_free_mb:
        return  # unknown reading = NO-OP (never kill on missing data); healthy = done
    state.log_line(
        "daemon",
        f"memory-guard: free {free_mb}MB < {min_free_mb}MB floor — scanning for a runaway",
    )
    snapshot = gs.global_state_dir() / "memory-guard.ps-snapshot.txt"
    rows = mg.snapshot_processes(str(snapshot))
    protected = frozenset({os.getpid(), os.getppid()})
    min_age = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_MEMORY_GUARD_RUNAWAY_ETIME_S"),
        mg.DEFAULT_RUNAWAY_ETIME_S,
    )
    victim = mg.select_victim(rows, protected_pids=protected, min_etime_s=min_age)
    if victim is None:
        state.log_line(
            "daemon",
            "memory-guard: pressure but NO Tier-1 candidate (only janitor-owned "
            "runaways are killable) — standing down; snapshot kept at "
            f"{snapshot}",
        )
        # S6 (TRDD-1T53EKTN): standing down must not mean SILENCE about a giant we
        # rightly won't kill — the 39 GB fseventsd grew unnoticed exactly here. Alert
        # (once per distinct hog, emit_once-deduped) with the S7 dual disk metric so a
        # human can judge whether "low disk" is real or purgeable-covered.
        alert_rss_kb = state.coerce_int(
            os.environ.get("CLAUDE_PLUGIN_OPTION_MEMORY_GUARD_ALERT_RSS_KB"),
            mg.DEFAULT_ALERT_RSS_KB,
        )
        if alert_rss_kb > 0:
            hog = mg.select_refused_alert(
                rows, protected_pids=protected, min_etime_s=min_age, min_rss_kb=alert_rss_kb
            )
            if hog is not None:
                seen = gs.global_state_dir() / "memory-guard-alert-seen.txt"
                # Key on the program, not the pid: the same runaway respawning under a
                # new pid is the SAME problem and must not re-alert every beat.
                key = f"{hog.command.split()[0] if hog.command else '?'}:{alert_rss_kb}"
                msg = dedupe.emit_once(
                    seen,
                    key,
                    "memory-guard ALERT: unkillable runaway "
                    f"pid={hog.pid} rss={hog.rss_kb // 1024}MB age={hog.etime_s}s "
                    f"cmd={hog.command!r} — the never-kill invariant holds (not "
                    f"janitor-owned); a HUMAN must decide. Disk: {dp.disk_pressure().label}. "
                    f"Free memory was {free_mb}MB; snapshot: {snapshot}",
                )
                if msg:
                    state.log_line("daemon", msg)
        return
    killed = mg.kill_process(victim.pid)
    state.log_line(
        "daemon",
        f"memory-guard: {'KILLED' if killed else 'KILL FAILED for'} runaway "
        f"pid={victim.pid} rss={victim.rss_kb}KB age={victim.etime_s}s "
        f"cmd={victim.command!r} (free was {free_mb}MB; snapshot: {snapshot})",
    )


def _plugins_cache_root() -> Path:
    """Resolve `<config>/plugins/cache` — the parent of every marketplace's
    cached plugins. The daemon itself lives inside this tree
    (`<cache>/<mkt>/<plugin>/<ver>/scripts/daemon.py`), so walk up to the `cache`
    dir whose parent is `plugins`; fall back to the HOME/CLAUDE_CONFIG_DIR path."""
    for p in _HERE.parents:
        if p.name == "cache" and p.parent.name == "plugins":
            return p
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(cfg) / "plugins" / "cache"


def task_cache_prune() -> None:
    """Prune stale plugin-cache version dirs (TRDD-a6d2fdaf, Fix A).

    The cache `~/.claude/plugins/cache/<mkt>/<plugin>/<version>/` grows without
    bound: a fast-publishing plugin (CPV ships several versions a DAY) leaves
    dozens of stale version dirs, and Claude Code's ~7-day GC keeps them all
    because they are each 'recent' — on this machine CPV alone reached 49 cached
    versions and the cache hit 4.5 GB. The daemon owns this because the cache is
    machine-global (scope invariant, issue #7).

    Cardinal safety: NEVER prune a version a LIVE session might still have loaded.
    Per plugin we keep {pinned ∪ newest-N}; of the rest, a version is removed only
    when its dir mtime predates the cutoff — and the cutoff is pulled back behind
    the OLDEST live `claude` session's start (+ a margin), so a long unattended
    fleet session (the very thing the janitor protects) never has the version it
    loaded deleted out from under it. A cache dir is regeneratable (re-downloaded
    on demand), so the delete is safe and reversible-by-redownload.
    """
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_CACHE_PRUNE_ENABLED", True):
        return
    cache_root = _plugins_cache_root()
    if not cache_root.is_dir():
        return
    keep_recent = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_CACHE_PRUNE_KEEP_RECENT"), 5
    )
    min_age_days = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_CACHE_PRUNE_MIN_AGE_DAYS"), 7
    )
    margin_hours = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_CACHE_PRUNE_SESSION_MARGIN_HOURS"), 24
    )
    now = int(time.time())

    # Snapshot ps TO A FILE (no-self-match discipline) and find the oldest live
    # claude session; the cutoff is pulled back behind it so its loaded version
    # is protected.
    snapshot = gs.global_state_dir() / "cache-prune.ps-snapshot.txt"
    rows = mg.snapshot_processes(str(snapshot))
    sessions = [(r.command, r.etime_s) for r in rows]
    oldest_start = cp.oldest_claude_session_start(sessions, now)
    cutoff = cp.prune_cutoff(
        now=now,
        min_age_s=min_age_days * 86400,
        oldest_session_start=oldest_start,
        session_margin_s=margin_hours * 3600,
    )

    installed: dict = {}
    ip_path = cache_root.parent / "installed_plugins.json"
    try:
        installed = json.loads(ip_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        installed = {}  # no pin info → keep_recent still protects the current version

    plans = cp.plan_cache_prune(
        cache_root, installed, keep_recent=keep_recent, cutoff_epoch=cutoff, now=now
    )
    if not plans:
        return
    removed, failed = cp.apply_prune_plan(plans)
    if not removed and not failed:
        return
    sess_note = (
        f"oldest live session ~{(now - oldest_start) // 3600}h old"
        if oldest_start is not None
        else "no live session"
    )
    state.log_line(
        "daemon",
        f"cache-prune: removed {len(removed)} stale version dir(s) across "
        f"{len(plans)} plugin(s) (kept pinned + newest {keep_recent}; cutoff "
        f"{(now - cutoff) // 86400}d back; {sess_note})"
        + (f"; {len(failed)} delete(s) FAILED" if failed else ""),
    )
    for rel in removed[:20]:  # cap the log; the count above is the full total
        state.log_line("daemon", f"  cache-prune removed: {rel}")


def _recovery_state_path(rec_dir: Path, project_root: str) -> Path:
    """Per-instance recovery-state file, keyed by a filesystem-safe slug of the
    project root (the identity fleet_scan + the dashboard both use)."""
    slug = re.sub(r"[^A-Za-z0-9_.-]", "_", project_root).strip("_") or "root"
    return rec_dir / f"{slug}.json"


def _read_recovery_state(path: Path) -> dict:
    """Load an instance's {attempts, last_ts, alerted, identity}; {} when absent or
    corrupt. Valid-JSON-but-not-an-object (e.g. a bare list/number from external
    tampering) is treated as corrupt → {}, so one malformed file degrades to a fresh
    budget for that instance instead of crashing the whole beat with AttributeError."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_recovery_state(path: Path, st: dict) -> None:
    """Persist recovery state atomically (tmp + os.replace). Cleans up the tmp file
    if the rename fails, so a cross-device/perms error can't litter orphans."""
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(st), encoding="utf-8")
    try:
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _hard_restart_plan(inst) -> dict | None:
    """Build the hard-restart plan for a `dead`/`frozen`-exhausted instance
    (TRDD-56d24c02 increment 2). PURE dict building — nothing fires here.

    - `dead` (pid gone) → rung 5 `relaunch`: type ``claude --continue`` into the
      surviving pane. No kill, so no resurrect fallback — resurrect KILLS, and
      ``is_killable`` is frozen-only by design (a dead instance has no live pid
      worth killing); an unreachable dead pane is logged, never force-handled.
    - `frozen` (ladder exhausted) → rung 6 `force_restart` (kill the wedged pid +
      relaunch in its pane); when NO pane channel resolves, fall back to rung 7
      `resurrect` (detached background claude that kills + relaunches) — the
      documented no-channel escalation on ``build_force_restart``.
    """
    if inst.diagnosis == "dead":
        return fleet_restart.build_relaunch(inst.terminal)
    plan = fleet_restart.build_force_restart(inst.pid, inst.terminal)
    if plan is None:
        plan = fleet_restart.build_resurrect(inst.pid, inst.project_root)
    return plan


def _hard_restart_channel(plan: dict) -> str:
    """The audit-facing channel of a hard-restart plan: relaunch carries it at the
    top level, force_restart nests it under its relaunch sub-plan, resurrect has no
    keystroke channel (it spawns a detached process)."""
    ch = plan.get("channel") or plan.get("relaunch", {}).get("channel")
    return str(ch) if ch else "spawn"


def _run_hard_restart(inst, *, tag, fire, attempts, identity, sf, now, audit) -> None:
    """ONE hard-restart attempt (rungs 5-7) for a dead/frozen-exhausted instance
    (TRDD-56d24c02 increment 2). All kill-path gates live HERE, in order — each
    independently sufficient to stop a kill:

    1. plan build — relaunch/force_restart need a validated pane channel
       (tampered identities never reach argv/osascript); no channel on `dead`
       → log + audit, touch nothing.
    2. ``enabled`` — the beat's fire flag AND the DEFAULT-OFF opt-in
       ``fleet_restart.hard_restart_enabled()``. Off → ``fire_restart`` returns
       ``DRY_RUN:<rung>`` and executes NOTHING (the plan was still built, so the
       log shows exactly what WOULD happen).
    3. ``killable`` — ``fleet_restart.is_killable`` recomputed HERE from the live
       Instance facts (real claude cmdline, NOT ``active``, not this daemon,
       frozen-only): the second independent gate under ``diagnose_instance``'s
       guarantee that a transcript-advancing session is never frozen/dead.

    The attempt is consumed on DRY_RUN and FIRED alike — WHY: a permanently
    disabled or failing hard rung must still walk the 4-attempt budget to the
    crash-loop human alert (with the cooldown throttling its log line) instead of
    dry-run-logging every beat forever. A SUCCESSFUL restart gives the session a
    NEW pid → the identity stamp resets the budget for the new occupant, so
    consuming attempts here can never starve a recovered instance.
    """
    plan = _hard_restart_plan(inst)
    if plan is None:
        state.log_line(
            "daemon",
            f"session-liveness: {tag} UNREACHABLE ({inst.terminal}) — would "
            "hard-restart; skipped (no injection channel)",
        )
        audit(inst, "unreachable", "relaunch", None)  # plan is None only on `dead`
        return
    enabled = fire and fleet_restart.hard_restart_enabled()
    killable = fleet_restart.is_killable(
        pid=inst.pid,
        command=inst.command,
        active=inst.active,
        diagnosis=inst.diagnosis,
        self_pid=os.getpid(),
        daemon_pid=gs.daemon_pid(),
    )
    outcome = fleet_restart.fire_restart(plan, enabled=enabled, killable=killable)
    _write_recovery_state(sf, {"attempts": attempts + 1, "last_ts": now, "identity": identity})
    rung = str(plan.get("rung", "?"))
    channel = _hard_restart_channel(plan)
    state.log_line("daemon", f"session-liveness: {outcome} → {channel} for {tag}")
    # Audit outcome = the fire_restart status class, greppable lowercase
    # (dry_run / fired / fire_failed / refused / unknown_rung).
    audit(inst, outcome.split(":", 1)[0].lower(), rung, channel)


def task_rules_cleanup() -> None:
    """Post-uninstall orphaned-rule cleanup (TRDD-H9IBY95W).

    Claude Code has NO uninstall hook and does not remove a plugin's `~/.claude/rules/`
    files on uninstall, so the janitor's installed rules would sit forever as orphans.
    This daemon beat is the only actor that can remove them after a FULL uninstall: the
    daemon keeps running from its now-orphaned cache for up to ~7 days (until the cache is
    GC'd), a window in which the plugin's own hooks can no longer fire. When — and ONLY
    when — the janitor is CONFIRMED fully uninstalled (referenced in no settings.json
    scope AND its data dir gone), it removes the provenance-marked janitor rules from the
    USER `~/.claude/rules/` dir. It NEVER touches a user's own rule (marker-gated) and
    NEVER touches any MEMORY store. Opt out with CLAUDE_PLUGIN_OPTION_RULES_CLEANUP_ENABLED=0.
    """
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_RULES_CLEANUP_ENABLED", True):
        return
    removed = ri.cleanup_user_orphans_if_uninstalled()
    if removed:
        state.log_line(
            "daemon",
            f"janitor uninstalled → removed {len(removed)} orphaned user-scope rule(s): "
            + ", ".join(removed),
        )


def task_session_liveness(fleet: list | None = None) -> None:
    """Fleet-guardian beat (TRDD-324223a6, A2): detect frozen / cron-dead /
    version-mismatched claude instances across the WHOLE host and recover them from
    OUTSIDE by injecting ESC + /janitor-arm (or /reload-plugins) into each one's OWN
    terminal — the immortality the in-session cron cannot provide, because the cron
    is the very thing that died in the 20-hour freeze.

    SAFETY (load-bearing): diagnose_instance NEVER classifies a session whose
    transcript is advancing as recoverable, so an actively-working session is never
    touched, and a `disarmed.flag` session is sacrosanct. The three gentle rungs
    (rearm/reload/update) are idempotent — harmless even if fired on a merely-idle
    session (ESC is a no-op with no in-flight turn; the slash-commands just
    re-establish the heartbeat). Per-instance cooldown + a crash-loop guard bound
    it; on the guard trip a human is alerted ONCE.

    HARD-RESTART rungs (A5, TRDD-56d24c02 increment 2 — USER-approved 2026-07-08):
    a `dead` instance gets rung 5 `relaunch`; a `frozen` instance whose gentle
    ladder is exhausted escalates to rung 6 `force_restart` (→ rung 7 `resurrect`
    when no pane resolves). These EXECUTE only when BOTH the beat's fire flag AND
    the separate DEFAULT-OFF opt-in CLAUDE_PLUGIN_OPTION_FLEET_HARD_RESTART_ENABLED=1
    hold; otherwise the built plan is dry-run-logged. Every kill path re-checks
    ``fleet_restart.is_killable`` (real claude cmdline, not `active`, not
    self/daemon, frozen-only) — the second gate under ``diagnose_instance``'s
    guarantee that a transcript-advancing session is never frozen/dead. A dry-run
    or fired hard attempt still consumes an attempt from the same 4-attempt budget,
    so a disabled or failing hard rung walks to the crash-loop human alert instead
    of logging forever.

    DETECTION always runs and logs. FIRING is on by default for the gentle rungs;
    set CLAUDE_PLUGIN_OPTION_FLEET_RECOVERY_ENABLED=0 for dry-run-log-only, or turn
    the whole beat off via CLAUDE_PLUGIN_OPTION_SESSION_LIVENESS_ENABLED=0.

    `fleet` is a test seam: pass pre-built ``fleet_scan.Instance`` rows to exercise
    the REAL decision/audit/state wiring without scanning the host process table
    (execution stays opt-in-gated, so tests never touch a live process).
    """
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_SESSION_LIVENESS_ENABLED", True):
        return
    fire = state.is_truthy_env("CLAUDE_PLUGIN_OPTION_FLEET_RECOVERY_ENABLED", True)
    now = int(time.time())
    # janitor#77 item C: only dispatch.py clears a rate-limited.flag, and dispatch needs a
    # live cron — so a cron-dead project can never clear its own. The daemon is alive when
    # the cron is not. Sweeping here (0 disables) restores the honest `cron_dead` diagnosis,
    # and with it the gentle `rearm` rung instead of `frozen`'s walk toward a force_restart.
    sweep_s = 3600 * _env_interval("CLAUDE_PLUGIN_OPTION_RATE_LIMIT_FLAG_MAX_AGE_HOURS", 24)
    if fleet is None:
        try:
            fleet = fleet_scan.gather_fleet(now=now, sweep_stale_rate_limit_s=sweep_s)
        except Exception as exc:  # noqa: BLE001 - a scan error must never kill the beat
            state.log_line("daemon", f"session-liveness: fleet scan failed: {exc}")
            return
    rec_dir = gs.global_state_dir() / "recovery"
    rec_dir.mkdir(parents=True, exist_ok=True)

    def _audit(inst, outcome: str, rung: str | None, channel: str | None) -> None:
        """Append ONE recovery-decision record to the F3 audit log (TRDD-F3AUDLOG).

        FAIL-OPEN belt-and-suspenders: ra.record_recovery is already fully guarded
        (an audit fault returns None, never raises), but we re-wrap here too so that
        even an unexpected error constructing the args can NEVER perturb the recovery
        beat — the audit is a pure side-channel; the beat's logic stays untouched.
        """
        try:
            ra.record_recovery(
                ts=now,
                project_root=inst.project_root,
                pid=inst.pid,
                tty=inst.tty,
                diagnosis=inst.diagnosis,
                rung=rung,
                channel=channel,
                outcome=outcome,
            )
        except Exception:  # noqa: BLE001 -- an audit fault must NEVER crash the recovery beat
            pass

    for inst in fleet:
        if not inst.project_root:
            continue  # no .janitor project → nothing to re-arm; can't key state
        sf = _recovery_state_path(rec_dir, inst.project_root)
        if sl.recovery_for_diagnosis(inst.diagnosis) is None:
            # healthy / unarmed → never poke, and CLEAR any stale attempt counter so
            # a later freeze — or a different session that reuses this project dir —
            # starts with a fresh budget instead of inheriting a spent/alerted one.
            if sf.exists():
                sf.unlink(missing_ok=True)
            continue
        st = _read_recovery_state(sf)
        # Identity-stamp: bind the budget to THIS exact session (pid+tty). If the
        # stored identity differs (a restart → new pid, or a stale file a vanished
        # session left behind), discard it — a freshly-restarted session must never
        # inherit the previous occupant's spent/alerted budget and be refused help.
        identity = f"{inst.pid}:{inst.tty or ''}"
        if st.get("identity") != identity:
            st = {}
        attempts = state.coerce_int(
            str(st.get("attempts", 0)), 0, detector_name="session-liveness", var_name="attempts"
        )
        tag = f"{os.path.basename(inst.project_root)} [{inst.diagnosis}] attempt={attempts}"
        decision = fr.gate(last_ts=st.get("last_ts"), attempts=attempts, now=now)
        if decision == "crash_loop":
            if not st.get("alerted"):  # alert ONCE, not every beat
                state.log_line(
                    "daemon",
                    f"session-liveness: GIVING UP on {tag} after {attempts} attempts "
                    "— recovery is looping; a human must intervene",
                )
                st["alerted"] = True
                st["identity"] = identity
                _write_recovery_state(sf, st)
                # Audit ONCE too (gated on the same not-yet-alerted flag) so a
                # permanently-looping instance records the give-up exactly once
                # rather than appending every beat forever.
                _audit(inst, "declined_crash_loop", None, None)
            continue
        if decision == "cooldown":
            continue
        action = fr.action_for(inst.diagnosis, attempts, include_hard=True)
        if action is None:
            # Unknown / unrecoverable diagnosis — we never invent an action for a
            # state we don't recognize. (Since increment 2 wired A5, `dead` maps to
            # the hard rung `relaunch` and no longer lands here.)
            _audit(inst, "declined_unwired", action, None)
            continue
        if sl.is_hard_rung(action):
            # A5 hard-restart rungs (TRDD-56d24c02 increment 2). Extracted so the
            # kill-path gates live in ONE reviewed place; executes only behind the
            # DEFAULT-OFF opt-in — else dry-run-logs the built plan.
            _run_hard_restart(
                inst, tag=tag, fire=fire, attempts=attempts,
                identity=identity, sf=sf, now=now, audit=_audit,
            )
            continue
        # Hard (ESC) only for a frozen target — a live cron_dead/version_mismatch
        # session gets a soft enqueue so its in-flight turn survives (TRDD-0GPQROC1).
        plan = fleet_inject.build_injection(
            inst.terminal, action, esc_first=fr.injection_is_hard(inst.diagnosis)
        )
        if plan is None:
            state.log_line(
                "daemon",
                f"session-liveness: {tag} UNREACHABLE ({inst.terminal}) — would "
                f"{action}; skipped (no injection channel)",
            )
            # No injection channel exists (that's WHY it's unreachable), so channel=None.
            _audit(inst, "unreachable", action, None)
            continue
        if not fire:
            state.log_line(
                "daemon", f"session-liveness:DRY would {action} → {plan['channel']} for {tag}"
            )
            _audit(inst, "dry_run", action, str(plan["channel"]))
            continue
        ok = fleet_inject.fire(plan)
        _write_recovery_state(
            sf, {"attempts": attempts + 1, "last_ts": now, "identity": identity}
        )
        state.log_line(
            "daemon",
            f"session-liveness: {'FIRED' if ok else 'FIRE-FAILED'} {action} → "
            f"{plan['channel']} for {tag}",
        )
        _audit(inst, "fired" if ok else "fire_failed", action, str(plan["channel"]))


def _fire_fleet_stop(inst, plan: dict, flag_state: str, now: int) -> None:
    """Fire ONE fleet-stop injection through the validated tmux/iTerm channel, stamp on
    a successful fire (so a held flag hits each session once), and F3-audit (fail-open).
    Extracted from task_fleet_stop so the beat stays under the complexity cap; `inst`
    is the fleet Instance (for audit fields) or None."""
    # SOFT (no ESC, TRDD-0GPQROC1): a machine-wide pause/disarm should land at each
    # session's turn boundary — the enqueued command runs when the turn ends, so the
    # stop never destroys in-flight work (user directive 2026-07-10).
    #
    # EXCEPT a FROZEN target (code-review finding, 2026-07-11): a wedged turn never
    # ends, so a softly-typed /janitor-disarm would sit in its input queue forever —
    # yet fire() succeeds, record_fleet_injection stamps (pid, flag) as delivered, and
    # the stop is NEVER retried while the flag is held. The frozen session's cron would
    # keep firing billable turns straight through a machine-wide stop. The ESC IS the
    # unwedge, so reuse the SAME policy the gentle-recovery path uses (fleet_recovery.
    # injection_is_hard) instead of hard-coding soft. `inst` is None only when the
    # scanned fleet lost the pid between scan and fire — then stay soft (no diagnosis
    # to justify killing a turn).
    esc_first = fr.injection_is_hard(inst.diagnosis) if inst is not None else False
    cmd_plan = fleet_restart.command_injection_plan(
        plan["terminal"], plan["command"], esc_first=esc_first
    )
    if cmd_plan is None:
        state.log_line(
            "daemon",
            f"fleet-stop: pid {plan['pid']} UNREACHABLE ({plan['terminal']}) — "
            f"would {plan['command']}; skipped (no injection channel)",
        )
        return
    ok = fleet_inject.fire(cmd_plan)
    if ok:
        # Stamp ONLY on a successful fire, so a transient fire failure retries next beat.
        gs.record_fleet_injection(plan["pid"], flag_state, now)
    state.log_line(
        "daemon",
        f"fleet-stop: {'FIRED' if ok else 'FIRE-FAILED'} {plan['command']} → "
        f"{cmd_plan['channel']} for pid {plan['pid']} [{flag_state}]",
    )
    if inst is not None:
        try:
            ra.record_recovery(
                ts=now,
                project_root=inst.project_root,
                pid=inst.pid,
                tty=inst.tty,
                diagnosis=inst.diagnosis,
                rung=f"fleet-stop:{flag_state}",
                channel=str(cmd_plan["channel"]),
                outcome="fired" if ok else "fire_failed",
            )
        except Exception:  # noqa: BLE001 -- an audit fault must NEVER crash the beat
            pass


def task_fleet_stop() -> None:
    """Daemon-driven fleet disarm/pause beat (TRDD-ME8V2YJF): when the machine-wide
    disarm (kill-switch) or pause flag is set, type the STOP command into every OTHER
    running janitor session so an ALREADY-armed fleet stops with NO human present — the
    reach-every-session half of the self-disarm story (RQ9FIFX6 is the in-session half,
    inert on crons baked before it shipped). REUSES the freeze-recovery machinery:
    fleet_scan discovery + the validated tmux/iTerm channel (fleet_restart) + fleet_inject.fire.

    SAFETY (three gates, mirroring the hard-restart rungs):
    1. DEFAULT-OFF — CLAUDE_PLUGIN_OPTION_FLEET_STOP_ENABLED=1 to arm. Typing into
       another session's pane is powerful, so it ships INERT (no-op until opted in).
    2. NEVER this process, the daemon, a non-claude pid, or a session whose transcript
       is ADVANCING (inst.active → the user's live work) — fleet_stop.is_injectable.
    3. DEDUPE per (pid, flag): a held flag injects each session exactly once
       (global_state stamps); clearing the flag forgets the stamps so a re-set re-injects.
    Never raises — a scan fault logs and returns.
    """
    if not fleet_stop.fleet_stop_enabled():
        return  # dormant until the user opts in — the whole capability ships inert
    flag_state = gs.fleet_stop_flag_state()
    if flag_state is None:
        # No fleet-stop flag set → forget every stamp so a FUTURE disarm/pause re-injects
        # each session fresh (else a stamp from a prior flag would suppress the next one).
        gs.clear_fleet_injections(None)
        return
    now = int(time.time())
    try:
        fleet = fleet_scan.gather_fleet(now=now)
    except Exception as exc:  # noqa: BLE001 - a scan error must never kill the beat
        state.log_line("daemon", f"fleet-stop: fleet scan failed: {exc}")
        return
    by_pid = {i.pid: i for i in fleet}
    sessions = [{"pid": i.pid, "command": i.command, "terminal": i.terminal} for i in fleet]
    plans = fleet_stop.select_stop_targets(
        sessions,
        flag_state=flag_state,
        self_pid=os.getpid(),
        daemon_pid=gs.daemon_pid(),
        already_injected=gs.fleet_injections_seen(),
        user_active_pids={i.pid for i in fleet if i.active},
    )
    for p in plans:
        _fire_fleet_stop(by_pid.get(p["pid"]), p, flag_state, now)


class Task:
    """One periodic unit of work owned by the daemon.

    The cadence stamp (`last-run.ts`) lives under the global state dir so
    it survives daemon restarts (the next daemon picks up where the previous
    left off). `time_until_due()` lets the main loop sleep precisely until
    the soonest task is ready instead of busy-polling.
    """

    def __init__(self, name: str, interval_s: int, fn: Callable[[], None]) -> None:
        self.name = name
        self.interval_s = interval_s
        self.fn = fn
        self.last_run_path = gs.global_state_dir() / f"{name}.last-run.ts"
        # Consecutive-failure streak (Pillar 1). Lives beside last-run.ts so a
        # quarantine SURVIVES daemon restarts — a broken task does not get a clean
        # slate just because the daemon respawned. Reset to 0 on the first success.
        self.failcount_path = gs.global_state_dir() / f"{name}.failcount"

    def _last_run(self) -> int:
        return state.read_int_state(self.last_run_path, 0)

    def _failcount(self) -> int:
        return state.read_int_state(self.failcount_path, 0)

    def _backoff_penalty(self, fails: int) -> int:
        """Quarantine backoff added on top of the cadence: 0 until
        _TASK_BACKOFF_AFTER_FAILS consecutive failures, then interval * 2**(fails-K),
        capped at _TASK_MAX_BACKOFF_SEC. Keeps a permanently-broken task from
        re-running every tick while still retrying a recovered one within the hour."""
        if fails < _TASK_BACKOFF_AFTER_FAILS:
            return 0
        shift = min(fails - _TASK_BACKOFF_AFTER_FAILS, 16)  # cap the exponent (2**16 is already huge)
        return min(self.interval_s * (2 ** shift), _TASK_MAX_BACKOFF_SEC)

    def time_until_due(self) -> int:
        penalty = self._backoff_penalty(self._failcount())
        return max(0, self._last_run() + self.interval_s + penalty - int(time.time()))

    def is_due(self) -> bool:
        return self.time_until_due() == 0

    def run(self) -> None:
        state.log_line("daemon", f"task '{self.name}' starting")
        t0 = time.time()
        failed = False
        try:
            self.fn()
        except Exception as exc:  # noqa: BLE001 - never propagate a task error
            failed = True
            state.log_line("daemon", f"task '{self.name}' raised: {exc}")
        finally:
            dt = int(time.time() - t0)
            state.atomic_write(self.last_run_path, str(int(time.time())))
            # Pillar-1 supervision: a success clears the streak; each consecutive
            # failure increments it so time_until_due() quarantines the task with
            # exponential backoff instead of re-running it every cadence.
            if failed:
                fails = self._failcount() + 1
                state.atomic_write(self.failcount_path, str(fails))
                penalty = self._backoff_penalty(fails)
                note = f" — quarantined, next run +{penalty}s" if penalty else ""
                state.log_line(
                    "daemon",
                    f"task '{self.name}' FAILED in {dt}s (consecutive={fails}){note}",
                )
            else:
                if self._failcount():
                    state.atomic_write(self.failcount_path, "0")  # recovered → reset the streak
                state.log_line("daemon", f"task '{self.name}' done in {dt}s")


def _build_tasks() -> list[Task]:
    return [
        Task("marketplace-refresh", _INTERVAL_MARKETPLACE_REFRESH, task_marketplace_refresh),
        Task("user-plugins-update", _INTERVAL_USER_PLUGINS_UPDATE, task_user_plugins_update),
        Task("version-update", _INTERVAL_VERSION_UPDATE, task_version_update),
        Task("oauth-rotator-supervisor", _INTERVAL_OAUTH_SUPERVISOR,
             task_oauth_rotator_supervisor),
        Task("oauth-rotator-tick", _INTERVAL_OAUTH_TICK, task_oauth_rotator_tick),
        Task("memory-guard", _INTERVAL_MEMORY_GUARD, task_memory_guard),
        Task("cache-prune", _INTERVAL_CACHE_PRUNE, task_cache_prune),
        Task("rules-cleanup", _INTERVAL_RULES_CLEANUP, task_rules_cleanup),
        Task("session-liveness", _INTERVAL_SESSION_LIVENESS, task_session_liveness),
        Task("fleet-stop", _INTERVAL_FLEET_STOP, task_fleet_stop),
    ]


# The only task(s) allowed to run while the daemon is idling under global MAINTENANCE
# (see the `main()` maintenance branch below). Keep this to genuine keepalive-critical
# work only — everything else in `tasks` is exactly what maintenance means to skip.
_MAINTENANCE_KEEPALIVE_TASK_NAMES = frozenset({"oauth-rotator-tick"})


def _run_maintenance_keepalive(tasks: list[Task]) -> None:
    """Run ONLY the keepalive-critical task(s) while otherwise idling under MAINTENANCE.

    B3 bug fix: the maintenance branch in `main()` used to `continue` straight past the
    ENTIRE task list, so "oauth-rotator-tick" (the 60 s beat that refreshes the LIVE
    OAuth credential — see `task_oauth_rotator_tick`) never ran under maintenance.
    Maintenance keeps every session firing CHEAP (the CLAUDE.md contract), so a lapsed
    token would break the whole fleet while it looked idle. This runs ONLY the task(s)
    named in `_MAINTENANCE_KEEPALIVE_TASK_NAMES` — the alert-only
    "oauth-rotator-supervisor" and everything else stay skipped, matching maintenance's
    "idle the expensive workloads" intent. Goes through the Task object (not a bare
    `task_oauth_rotator_tick()` call) so the normal cadence stamp + failure-backoff
    bookkeeping in `Task.run()` still applies.
    """
    for task in tasks:
        if task.name in _MAINTENANCE_KEEPALIVE_TASK_NAMES and task.is_due():
            task.run()


def _setup_os_keepalive() -> None:
    """Best-effort L0 OS-keepalive setup at daemon startup (singleton only — runs after the
    flock is held). Refresh the DATA closure from the FRESHEST cache so a future OS respawn
    runs current code, then register the OS service ONCE. Registration is gated on
    `not is_installed()` because re-running it on the launchd-spawned daemon's OWN startup
    would bootout the running process — a self-kill loop (TRDD-71ABD7V7). Never raises."""
    try:
        if not ka.opted_in():
            return
        src = ka.latest_cache_scripts_dir() or _HERE
        try:
            ka.restage(src)  # refresh DATA (safe: no OS activation, no bootout)
        except OSError as exc:
            state.log_line("daemon", f"os-keepalive restage skipped: {exc}")
        if not ka.is_installed():
            ok, msg = ka.activate()
            state.log_line("daemon", f"os-keepalive activate: ok={ok} ({msg})")
    except Exception as exc:  # noqa: BLE001 — keepalive must NEVER kill the daemon it protects
        state.log_line("daemon", f"os-keepalive setup skipped: {exc}")


def _keepalive_self_heal() -> bool:
    """For the OS-spawned (`--keepalive`) daemon ONLY: when a newer cache version exists,
    re-stage it into DATA and return True to signal a graceful exit so launchd respawns on
    the fresh code (the launched entry path is stable; only the daemon.py beside it is
    refreshed). Returns False (keep running) otherwise. Exits ONLY after verifying the
    re-stage actually made the staged code current, so a persistent copy failure can't loop
    exit→respawn→exit. Never raises."""
    if not _KEEPALIVE_INSTANCE:
        return False
    try:
        if not ka.opted_in():
            return False
        src = ka.latest_cache_scripts_dir()
        if src is None or ka.staged_is_current(src):
            return False
        ka.restage(src)
        if ka.staged_is_current(src):
            state.log_line("daemon", "os-keepalive: newer version staged → exit for respawn")
            return True
    except Exception as exc:  # noqa: BLE001
        state.log_line("daemon", f"os-keepalive self-heal skipped: {exc}")
    return False


def _uninstall_os_keepalive() -> None:
    """Best-effort: remove the OS keepalive on a machine-wide kill-switch stop so launchd
    never resurrects a daemon the user deliberately disarmed. A no-op if nothing was
    installed. Never raises."""
    try:
        ok, msg = ka.uninstall()
        state.log_line("daemon", f"os-keepalive uninstall: ok={ok} ({msg})")
    except Exception as exc:  # noqa: BLE001
        state.log_line("daemon", f"os-keepalive uninstall skipped: {exc}")


def _repair_tool_path() -> None:
    """Give this daemon a PATH that can actually find its tools (TRDD-VQ4LX7ND).

    A launchd/systemd child inherits a bare PATH with no `/opt/homebrew/bin`, so
    `tmux` was unresolvable and `fleet_scan._run` swallowed the FileNotFoundError
    into "" — the guardian saw zero panes and skipped every rearm IN SILENCE (254
    consecutive `UNREACHABLE ({})` beats, while the same code fired 93 injections
    from a session-spawned daemon that had a login PATH). Must run before ANY
    subprocess, so both the scan probes and the keystroke sends can resolve.

    The missing-tool line is the other half of the fix: a dead recovery channel is
    now VISIBLE at startup instead of degrading into a mute skip loop.
    FAIL-OPEN — a PATH fault must never brick the daemon.
    """
    try:
        added = daemon_path.ensure_tool_path()
        if added:
            state.log_line("daemon", f"PATH augmented with: {os.pathsep.join(added)}")
        missing = [t for t, p in daemon_path.resolve_injection_tools().items() if p is None]
        if missing:
            state.log_line(
                "daemon",
                f"injection tools MISSING from this daemon's PATH: {', '.join(missing)} "
                "— the matching recovery channels cannot fire",
            )
    except Exception as exc:  # noqa: BLE001 — PATH repair is best-effort, never fatal
        state.log_line("daemon", f"PATH augmentation skipped: {exc}")


def main() -> int:
    # The daemon is a machine-wide singleton, but state.log_line() defaults to
    # a PROJECT-scoped logs/ dir keyed on whatever tree spawned us — so the
    # "global" daemon's log used to scatter into a random project's .janitor/
    # logs/ (issue #9: the per-session watchdog pointed users at
    # ~/.claude/janitor-global-state/daemon.log, which never existed). Pin the
    # daemon's log to the global-state dir BEFORE the first log_line() so it is
    # deterministic and the watchdog's `Inspect: <daemon.log>` path is real.
    # setdefault() lets tests/hosts override it.
    os.environ.setdefault("JANITOR_LOG_DIR", str(gs.global_state_dir()))

    gs.init_global_state()
    _repair_tool_path()

    # KEEPQRTN HIGH-2 — feed the crash-loop signal on the OS-respawn path. The crash-loop
    # breaker only counts spawn attempts written by the SESSION path (spawn_daemon_detached).
    # An OS keepalive (launchd/systemd) respawn execs this daemon directly, so a die-on-start
    # daemon respawned by the OS would loop forever invisibly to crash_loop_active() → C4
    # never quarantines the bad version. Record a spawn-attempt stamp HERE (earliest safe
    # point — after init_global_state so the state dir exists, before the flock so a daemon
    # that dies at/after the flock still counted its attempt) so the OS-driven crash loop is
    # visible to the breaker and C4 rolls the bad version back. ONLY on the keepalive path:
    # the session path already records via spawn_daemon_detached, so recording on both would
    # double-count and falsely trip the breaker. FAIL-OPEN: wrapped so a bookkeeping fault
    # can NEVER break daemon startup — this is the deepest immortality layer.
    if _KEEPALIVE_INSTANCE:
        try:
            gs.record_spawn_attempt()
        except Exception as exc:  # noqa: BLE001 — must never brick the OS-respawned daemon
            state.log_line("daemon", f"keepalive spawn-attempt record skipped: {exc}")

    # Singleton: the flock IS the truth. If we cannot acquire it, another
    # daemon is alive — exit silently. PID file / heartbeat are downstream
    # diagnostics; they cannot disagree with the kernel's flock state.
    # The OS-keepalive (L0) instance BLOCKS for the singleton instead of aborting: under
    # launchd/systemd KeepAlive, aborting on a held lock would busy-loop spawn→abort→respawn
    # while a session-spawned daemon holds it. Blocking makes it wait idle (zero churn) and
    # take over when the holder exits. A session-spawned daemon stays non-blocking (loser
    # exits). (TRDD-71ABD7V7.)
    flock_fd = gs.acquire_singleton_flock(blocking=_KEEPALIVE_INSTANCE)
    if flock_fd is None:
        return 0

    # TRDD-2U8AH82F: one-time staged handover legacy → plugin DATA dir. Runs ONLY
    # here — holding the (legacy-path) singleton flock proves we are the machine's
    # single writer. On success we hold BOTH flocks for this daemon's lifetime
    # (flock-moves-LAST: the NEW lock is taken before the marker flips resolution),
    # and every gs.* call below — including write_daemon_pid — resolves the NEW dir.
    # `new_flock_fd` must stay referenced: closing it would release the NEW lock.
    new_flock_fd = None
    try:
        new_flock_fd = gs.migrate_global_state_to_data_dir()
    except Exception as exc:  # noqa: BLE001 — migration must never brick startup
        state.log_line("daemon", f"global-state migration skipped: {exc}")
    if new_flock_fd is not None:
        # Re-pin the daemon log to the post-migration dir (log_dir() is lru_cached
        # and was resolved against the legacy dir at the top of main()). This is a
        # read-modify-write of the janitor's OWN private override var (never a
        # runtime-hijack var like PATH/LD_*); the value is the internally computed
        # DATA-dir path — no external input ever reaches the environment here. The
        # prior pin is read first and logged so the migration leaves an audit trail
        # of exactly which dir the log moved from (TRDD-82OP4EN9 publish gate).
        log_dir_var = "JANITOR_LOG_DIR"
        previous_pin = os.environ.get(log_dir_var)  # pre-migration (legacy) pin
        os.environ[log_dir_var] = str(gs.global_state_dir())
        state.log_dir.cache_clear()
        state.log_line(
            "daemon",
            f"global state migrated to the plugin DATA dir: {gs.global_state_dir()} "
            f"(TRDD-2U8AH82F; legacy dir kept as read-fallback; "
            f"log re-pinned from {previous_pin})",
        )

    pid = os.getpid()
    # Install the graceful-shutdown handlers BEFORE publishing the pid file.
    # The pid file is the public "I'm alive" signal a supervisor waits on before
    # SIGTERM'ing a stale daemon (request_daemon_restart). If the pid were
    # written first and a SIGTERM arrived in the window before these handlers
    # were installed, the DEFAULT SIGTERM disposition would kill the process
    # outright — skipping the `finally` below that calls remove_daemon_pid() —
    # and orphan a stale pid file (the intermittent
    # test_daemon_sigterm_graceful_shutdown failure: process dead, pid file
    # left behind). Handlers-first guarantees that once the pid file exists, any
    # SIGTERM runs _on_signal and unwinds through the finally, so cleanup always
    # runs and the pid file is removed.
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    try:
        signal.signal(signal.SIGHUP, _on_signal)  # nice-to-have on Unix
    except (AttributeError, ValueError):
        pass

    gs.write_daemon_pid(pid)
    gs.write_heartbeat()
    tasks = _build_tasks()
    state.log_line(
        "daemon",
        f"started (pid={pid}, tasks={[t.name for t in tasks]}, "
        f"intervals={[t.interval_s for t in tasks]})",
    )

    # L0 reboot/crash survival (TRDD-71ABD7V7): install (once) + refresh the OS keepalive so
    # a launchd/systemd service respawns this daemon even with ZERO Claude sessions — the
    # deepest immortality layer, closing the all-sessions-frozen gap that caused the 20-hour
    # freeze. This was held back in v0.16.0 because the pre-#152 CPV persistence gate could
    # not resolve an in-tree OS-keepalive installer and (correctly) flagged it. Issue #152
    # added the plugin-data-sandbox fold, so the installer now points the OS service at the
    # in-tree, CPV-scanned, provably-inert daemon_keepalive_entry.py and the gate resolves it
    # as a CLEAN persistence target — the discriminator used AS DESIGNED, not gamed (the entry
    # is genuinely exec/eval/network/listen-free). Best-effort, never fatal; a no-op when
    # CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE=0.
    _setup_os_keepalive()

    exit_reason = "signal"
    last_keepalive_check = 0.0  # wall-clock stamp gating the keepalive self-heal cadence
    try:
        while _running:
            if gs.kill_switch_present():
                # DISARM must reach every OTHER armed session BEFORE we exit: the loop
                # short-circuits here ahead of the task list, so the fleet-stop beat can
                # only act from this branch — a registered Task would NEVER run under a set
                # flag (the whole point of TRDD-ME8V2YJF's reach-every-session half). No-op
                # unless CLAUDE_PLUGIN_OPTION_FLEET_STOP_ENABLED=1 (ships dormant).
                task_fleet_stop()
                exit_reason = "kill-switch"
                break

            # A global MAINTENANCE (TRDD-FPL60EKV) idles the daemon's expensive task
            # workloads WITHOUT tearing it down and — unlike pause/disarm — WITHOUT stopping
            # any session: the sessions are meant to KEEP firing cheap (cache-refresh-only) to
            # stay warm, so this branch must NOT fleet-stop. Skip every task workload, keep
            # ticking the heartbeat (so we are not seen as wedged), and stay responsive — the
            # inner sleep breaks the instant maintenance lifts or a kill-switch/pause supersedes
            # it. Placed ABOVE the pause branch so maintenance wins when both are set, matching
            # dispatch's mode resolution (a session fires cheap, it is NOT disarmed).
            if gs.maintenance_mode_present():
                gs.write_heartbeat()
                # B3 fix: run the keepalive-critical task(s) (oauth-rotator-tick) even
                # though every other task workload stays skipped under maintenance —
                # see _run_maintenance_keepalive's docstring for the WHY.
                _run_maintenance_keepalive(tasks)
                for _ in range(_LOOP_CEILING_SEC):
                    # Break on _running=False, a kill-switch (the true STOP → the daemon must
                    # exit via the while-top branch), or maintenance lifting — but NOT on a
                    # global-pause. Maintenance is checked ABOVE the pause branch (it WINS when
                    # both are set), so if pause also broke this sleep we would `continue`,
                    # re-enter maintenance, break instantly again, and busy-spin write_heartbeat
                    # at 100% CPU (/code-review B5). Maintenance keeps sleeping through a pause.
                    if (
                        not _running
                        or gs.kill_switch_present()
                        or not gs.maintenance_mode_present()
                    ):
                        break
                    time.sleep(1)
                continue

            # A global PAUSE (TRDD-a3fa4d5d) idles the daemon WITHOUT tearing it down:
            # skip every task workload, but keep ticking the heartbeat so other sessions
            # never see us as wedged, and stay responsive — the inner sleep breaks the
            # instant the pause lifts (or a kill-switch/disarm supersedes it), so unpause
            # resumes work within ~1 s with no re-spawn. This is the lighter sibling of
            # the kill-switch (which EXITS); a pause is a temporary, teardown-free silence.
            if gs.global_pause_present():
                # PAUSE must reach every OTHER armed session too: this branch `continue`s
                # BEFORE the task list, so the fleet-stop beat can only fire from here (a
                # registered Task never runs while a flag is set). Deduped per (pid,flag) +
                # opt-in-gated → a no-op unless FLEET_STOP_ENABLED=1 (TRDD-ME8V2YJF).
                task_fleet_stop()
                gs.write_heartbeat()
                for _ in range(_LOOP_CEILING_SEC):
                    if not _running or gs.kill_switch_present() or not gs.global_pause_present():
                        break
                    time.sleep(1)
                continue

            for task in tasks:
                # A flag set mid-loop skips the REMAINING tasks NOW, not after the current
                # (up to 1800s) task finishes — TRDD-ME8V2YJF component B. Pause + maintenance
                # join the kill-switch in the per-task gate so "immediately skip the chores"
                # actually holds; the top-of-loop pause/maintenance branches then idle.
                if (
                    not _running
                    or gs.kill_switch_present()
                    or gs.global_pause_present()
                    or gs.maintenance_mode_present()
                ):
                    break
                if task.is_due():
                    task.run()

            gs.write_heartbeat()

            # L0 self-heal (OS-spawned daemon ONLY): on a slow cadence, re-stage + exit for
            # respawn when a newer cache version exists, so it converges to current code with
            # no session involvement. Instant no-op for a session-spawned daemon.
            now_s = time.time()
            if _KEEPALIVE_INSTANCE and now_s - last_keepalive_check >= _INTERVAL_KEEPALIVE_SELF_HEAL:
                last_keepalive_check = now_s
                if _keepalive_self_heal():
                    exit_reason = "self-update-respawn"
                    break

            # Sleep precisely until the next task is due, but in 1-second
            # increments so signals interrupt promptly.
            next_due = min((t.time_until_due() for t in tasks), default=_LOOP_CEILING_SEC)
            sleep_for = max(1, min(_LOOP_CEILING_SEC, next_due))
            for _ in range(sleep_for):
                if not _running or gs.kill_switch_present():
                    break
                time.sleep(1)
    finally:
        if exit_reason == "kill-switch":
            # A machine-wide kill-switch (e.g. /janitor-global-disarm) is a deliberate stop —
            # remove the OS keepalive so launchd/systemd does not immediately resurrect us
            # (KeepAlive would otherwise fight the user's explicit disarm). NOT done on a
            # plain signal/self-update exit, where a respawn is exactly what we want.
            _uninstall_os_keepalive()
        state.log_line("daemon", f"stopping ({exit_reason})")
        gs.remove_daemon_pid()
        gs.release_singleton_flock(flock_fd)
        state.rotate_log_if_big("daemon")

    return 0


if __name__ == "__main__":
    sys.exit(main())
