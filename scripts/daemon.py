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
  * (Reserved) version-update auto-update — currently still handled by the
    per-session `version-update.py` detector; will be folded in here in a
    follow-up. The daemon's mere existence already prevents the worst of the
    pile-up because the per-session marketplace-refresh / user-plugins-update
    are now refactored no-ops.

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

import global_state as gs  # noqa: E402
import state  # noqa: E402

# Default cadences. Each is overridable via the matching env var (the
# per-session userConfig knobs in plugin.json end up here on spawn).
_INTERVAL_MARKETPLACE_REFRESH = int(
    os.environ.get("CLAUDE_PLUGIN_OPTION_DAEMON_MARKETPLACE_REFRESH_INTERVAL", "1800")
)  # 30 min — daemon is the only writer; aggressive cadence is unnecessary.
_INTERVAL_USER_PLUGINS_UPDATE = int(
    os.environ.get("CLAUDE_PLUGIN_OPTION_DAEMON_USER_PLUGINS_UPDATE_INTERVAL", "3600")
)  # 1 h — full sweep takes ~7 min; hourly cadence keeps everything fresh.

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


def _run_workload(cmd: list[str], *, timeout: int = _WORKLOAD_TIMEOUT_SEC,
                  heartbeat_tick: int = _WORKLOAD_HEARTBEAT_TICK_SEC) -> Optional[subprocess.CompletedProcess[str]]:
    """Run a subprocess to completion, ticking the daemon heartbeat periodically.

    Returns the CompletedProcess on a normal exit (whatever the returncode),
    or None on timeout / spawn failure (already logged). The periodic
    heartbeat tick is what keeps the daemon visible to per-session liveness
    checks during a long `claude plugin marketplace update` (≈10 min).
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
            if time.time() > deadline or not _running or gs.kill_switch_present():
                state.log_line("daemon", f"  killing `{short}` (timeout or shutdown)")
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                return None


# ---------- Tasks --------------------------------------------------------

def task_marketplace_refresh() -> None:
    """Run `claude plugin marketplace update` (bulk → all marketplaces).

    This is the operation that, when fired from N concurrent sessions, was
    the worst contributor to the pile-up reported in issue #7. The daemon
    runs it exactly once per cadence — never overlapping with itself.
    """
    proc = _run_workload(["claude", "plugin", "marketplace", "update"])
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
    user_scope = [p for p in plugins
                  if isinstance(p, dict) and p.get("scope") == "user" and p.get("id")]
    total = len(user_scope)
    state.log_line("daemon", f"  user-plugins-update: {total} user-scope plugin(s)")
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

    def _last_run(self) -> int:
        return state.read_int_state(self.last_run_path, 0)

    def time_until_due(self) -> int:
        return max(0, self._last_run() + self.interval_s - int(time.time()))

    def is_due(self) -> bool:
        return self.time_until_due() == 0

    def run(self) -> None:
        state.log_line("daemon", f"task '{self.name}' starting")
        t0 = time.time()
        try:
            self.fn()
        except Exception as exc:  # noqa: BLE001 - never propagate a task error
            state.log_line("daemon", f"task '{self.name}' raised: {exc}")
        finally:
            dt = int(time.time() - t0)
            state.atomic_write(self.last_run_path, str(int(time.time())))
            state.log_line("daemon", f"task '{self.name}' done in {dt}s")


def _build_tasks() -> list[Task]:
    return [
        Task("marketplace-refresh", _INTERVAL_MARKETPLACE_REFRESH, task_marketplace_refresh),
        Task("user-plugins-update", _INTERVAL_USER_PLUGINS_UPDATE, task_user_plugins_update),
    ]


def main() -> int:
    gs.init_global_state()

    # Singleton: the flock IS the truth. If we cannot acquire it, another
    # daemon is alive — exit silently. PID file / heartbeat are downstream
    # diagnostics; they cannot disagree with the kernel's flock state.
    flock_fd = gs.acquire_singleton_flock()
    if flock_fd is None:
        return 0

    pid = os.getpid()
    gs.write_daemon_pid(pid)
    gs.write_heartbeat()
    tasks = _build_tasks()
    state.log_line(
        "daemon",
        f"started (pid={pid}, tasks={[t.name for t in tasks]}, "
        f"intervals=[{_INTERVAL_MARKETPLACE_REFRESH}, {_INTERVAL_USER_PLUGINS_UPDATE}])",
    )

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    try:
        signal.signal(signal.SIGHUP, _on_signal)  # nice-to-have on Unix
    except (AttributeError, ValueError):
        pass

    exit_reason = "signal"
    try:
        while _running:
            if gs.kill_switch_present():
                exit_reason = "kill-switch"
                break

            for task in tasks:
                if not _running or gs.kill_switch_present():
                    break
                if task.is_due():
                    task.run()

            gs.write_heartbeat()

            # Sleep precisely until the next task is due, but in 1-second
            # increments so signals interrupt promptly.
            next_due = min((t.time_until_due() for t in tasks), default=_LOOP_CEILING_SEC)
            sleep_for = max(1, min(_LOOP_CEILING_SEC, next_due))
            for _ in range(sleep_for):
                if not _running or gs.kill_switch_present():
                    break
                time.sleep(1)
    finally:
        state.log_line("daemon", f"stopping ({exit_reason})")
        gs.remove_daemon_pid()
        gs.release_singleton_flock(flock_fd)
        state.rotate_log_if_big("daemon")

    return 0


if __name__ == "__main__":
    sys.exit(main())
