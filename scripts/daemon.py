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

import global_state as gs  # noqa: E402
import state  # noqa: E402
import supervisor as oauth_supervisor  # noqa: E402  # scripts/oauth_rotator/supervisor.py
import version_update_lib as vu  # noqa: E402

# Default cadences. Each is overridable via the matching env var (the
# per-session userConfig knobs in plugin.json end up here on spawn).
_INTERVAL_MARKETPLACE_REFRESH = int(
    os.environ.get("CLAUDE_PLUGIN_OPTION_DAEMON_MARKETPLACE_REFRESH_INTERVAL", "1200")
)  # 20 min — daemon is the only writer of GLOBAL marketplace refresh
#  (refreshes every configured marketplace in one CLI call). The per-session
#  detector handles narrower local+project marketplaces at 5 min, so the
#  daemon doesn't need to be aggressive here.
_INTERVAL_USER_PLUGINS_UPDATE = int(
    os.environ.get("CLAUDE_PLUGIN_OPTION_DAEMON_USER_PLUGINS_UPDATE_INTERVAL", "3600")
)  # 1 h — full sweep takes ~7 min; hourly cadence keeps everything fresh.
_INTERVAL_VERSION_UPDATE = int(
    os.environ.get("CLAUDE_PLUGIN_OPTION_DAEMON_VERSION_UPDATE_INTERVAL", "21600")
)  # 6 h — janitor self-update cadence. GitHub releases land at human-day
#  granularity; checking every 6 h is plenty and keeps the load light.
_INTERVAL_OAUTH_SUPERVISOR = int(
    os.environ.get("CLAUDE_PLUGIN_OPTION_DAEMON_OAUTH_SUPERVISOR_INTERVAL", "600")
)  # 10 min — the opt-in OAuth-rotator governance/auto-heal task (TRDD-32acd15f
#  P2). A total no-op unless /janitor-auto-manage-oauth-on wrote the opt-in flag,
#  so this cadence is free for every non-opted-in install. When opted-in the
#  steady-state check is cheap (read the opt-in flag, stat the slots); the
#  SessionStart fast-path surfaces alert-only findings the moment a session starts.
_INTERVAL_OAUTH_TICK = int(
    os.environ.get("CLAUDE_PLUGIN_OPTION_DAEMON_OAUTH_TICK_INTERVAL", "60")
)  # 60 s — the opt-in OAuth-rotator beat (TRDD-32acd15f), folded into the daemon
#  per TRDD-f892e109 decision 3: this REPLACES the deleted launchd agent, which ran
#  the same `tick --only-if-claude-running` every 60 s via plist `StartInterval 60`.
#  A total no-op unless the opt-in flag is set AND the real Claude binary is running
#  (the guard lives inside cmd_tick). The daemon loop ceiling is already 60 s, so
#  this is the finest cadence the loop can offer.

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
                       heartbeat_tick: int = _WORKLOAD_HEARTBEAT_TICK_SEC) -> Optional[subprocess.CompletedProcess[str]]:
    """Run a subprocess ONCE to completion, ticking the daemon heartbeat periodically.

    Returns the CompletedProcess on a normal exit (whatever the returncode),
    or None on timeout / spawn failure (already logged). The periodic
    heartbeat tick is what keeps the daemon visible to per-session liveness
    checks during a long `claude plugin marketplace update` (≈10 min).

    This is the single-attempt primitive; `_run_workload` wraps it with the
    Pillar-1 retry-on-non-zero-exit policy.
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
                  max_attempts: int = _WORKLOAD_MAX_ATTEMPTS) -> Optional[subprocess.CompletedProcess[str]]:
    """Run a workload with the Pillar-1 retry policy (TRDD-7100178d Phase 4).

    Calls `_run_workload_once` up to `max_attempts` times, retrying ONLY on a
    non-zero exit (a crash / transient failure). A None result (spawn-failure or
    timeout-kill) and a clean rc==0 both return immediately — a missing binary
    won't reappear on a retry and a timed-out command already spent its budget.
    The retried exit code is logged so a recurring failure is visible. Every
    caller is idempotent (re-running a marketplace refresh / plugin update / usage
    probe has no side effect beyond the intended one), so a single retry is safe.
    """
    short = " ".join(cmd[:3]) + ("..." if len(cmd) > 3 else "")
    result: Optional[subprocess.CompletedProcess[str]] = None
    for attempt in range(1, max(1, max_attempts) + 1):
        result = _run_workload_once(cmd, timeout=timeout, heartbeat_tick=heartbeat_tick)
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
    _run_workload(
        [sys.executable, str(rotator_py), "tick", "--only-if-claude-running"],
        timeout=120,
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
    ]


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
        f"intervals={[t.interval_s for t in tasks]})",
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
