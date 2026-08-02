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

import contextlib
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
import findings_ledger  # noqa: E402  # the ONE finding choke point (TRDD-FENWWB4E)
import fleet_inject  # noqa: E402  # A3 terminal-env recovery injector (TRDD-324223a6)
import fleet_recovery as fr  # noqa: E402  # A2 recovery policy (TRDD-324223a6)
import fleet_restart  # noqa: E402  # raw-command channel builder reused by fleet-stop (TRDD-ME8V2YJF)
import fleet_scan  # noqa: E402  # fleet discovery + diagnosis (TRDD-324223a6)
import fleet_stop  # noqa: E402  # daemon-driven disarm/pause policy (TRDD-ME8V2YJF)
import github_config_audit as gca  # noqa: E402  # fleet GitHub-config audit (TRDD-157OH2D7)
import global_state as gs  # noqa: E402
import harness_backend  # noqa: E402  # server chore-ownership probe (TRDD-PZLVT2RN B2)
import launchd_keepalive as ka  # noqa: E402  # L0 OS keepalive install/uninstall (TRDD-71ABD7V7)
import memory_guard as mg  # noqa: E402  # Tier-1 OOM guard (TRDD-7100178d Pillar 4)
import notify  # noqa: E402  # human-notification channel — daemon-only (TRDD-4649ZLE0)
import recovery_audit as ra  # noqa: E402  # F3 recovery audit log (TRDD-F3AUDLOG) — fail-open side-channel
import rules_installer as ri  # noqa: E402  # post-uninstall orphaned-rule cleanup (TRDD-H9IBY95W)
import session_liveness as sl  # noqa: E402  # diagnosis→recovery mapping (TRDD-324223a6)
import state  # noqa: E402
import supervisor as oauth_supervisor  # noqa: E402  # scripts/oauth_rotator/supervisor.py
import user_intent  # noqa: E402  # hid_idle_seconds — the typing signal gating ALL injection (TRDD-6Q0OYYYH)
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
    "CLAUDE_PLUGIN_OPTION_DAEMON_MARKETPLACE_REFRESH_INTERVAL", 3600
)  # 1 h — daemon is the only writer of GLOBAL marketplace refresh
#  (refreshes every configured marketplace in one CLI call). The per-session
#  detector handles narrower local+project marketplaces at 5 min, and the
#  consumer of this refresh (user-plugins-update) runs hourly anyway, so a
#  faster beat buys nothing. WHY not the old 1200: the bulk refresh takes
#  ~1190 s at low priority, so a 1200 s cadence had the task running ~50% of
#  wall-clock time — and (pre-background-lane) starving the 60 s survival
#  beats for 20 min of every 40 (oauth-rotation starvation incident,
#  2026-07-17: an account hit its 5 h wall inside such a blind window).
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
_INTERVAL_GITHUB_CONFIG_AUDIT = _env_interval(
    "CLAUDE_PLUGIN_OPTION_DAEMON_GITHUB_CONFIG_AUDIT_INTERVAL", 21600
)  # 6 h — fleet-wide GitHub-config audit (TRDD-157OH2D7). READ-ONLY `gh` probes across the
#  ~13 ai-maestro plugin repos (rulesets / classic protection / workflows), writing findings
#  to a JSON the near-free per-session `fleet-github-config` detector surfaces. The daemon owns
#  it because it is fleet-scope machine-global work (issue #7 single-writer) — N sessions each
#  probing 13 repos would stampede the GitHub API. Branch rulesets change rarely, so 6 h is
#  ample; a no-op when `gh` is absent/unauthenticated.

# Loop ceiling — heartbeat tick interval upper bound. Must be << the
# staleness threshold (DEFAULT_DAEMON_STALE_SECONDS = 1800 s) so the heartbeat
# stays well within the alive window when no workload is running.
_LOOP_CEILING_SEC = 60

# Background bulk lane (oauth-rotation starvation incident, 2026-07-17). A due
# background task deferred by a busy lane — or one whose detached child is still
# running — re-checks on this beat instead of clamping the main-loop sleep to 1 s
# (which would busy-spin for the whole ~20 min of a bulk run). 5 s, not 60: the
# stamp lands at REAP time, so this beat bounds both a finished child's reap
# latency and the gap before the next queued bulk task spawns — and a lane-busy
# loop pass is just flag stats + one waitpid, so 5 s costs ~nothing.
#
# Env-tunable like every sibling cadence above. It was the ONE lane knob left
# hardcoded, and that made it unobservable from outside: a caller waiting on N
# queued bulk tasks pays this beat N times as pure latency with no way to shorten
# it, so a wait bound sized for the tasks' real work still goes red on the poll
# granularity alone (this flaked tests/test_daemon.py's 30 s two-task wait).
# max(1, …) is load-bearing: a 0 would clamp the main-loop sleep to a busy-spin
# for the whole ~20 min of a bulk run — the exact starvation this constant exists
# to prevent (oauth-rotation incident, 2026-07-17).
_BULK_RECHECK_SEC = max(
    1, _env_interval("CLAUDE_PLUGIN_OPTION_DAEMON_BULK_RECHECK_INTERVAL", 5)
)

# Grace added on top of _WORKLOAD_TIMEOUT_SEC before the parent hard-kills a
# detached background child. The child's own _run_workload caps should end it
# first; this is the belt for a child wedged OUTSIDE a workload subprocess.
_BULK_CHILD_KILL_GRACE_SEC = 120

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

    def _log(msg: str) -> None:
        state.log_line("daemon", f"  {msg}")

    if findings:
        res = oauth_supervisor.apply(findings, log=_log)
        state.log_line(
            "daemon",
            f"  oauth-rotator-supervisor: alerts={res.alerts or '[]'}",
        )
        # Human push (TRDD-4649ZLE0): every supervisor finding is BY DEFINITION an alert
        # only a human can act on (the supervisor heals nothing), and the rotator has no
        # project session to surface into — so the daemon's channel is the ONLY route.
        # notify's content-hash dedupe + daily cap keep a persistent condition from
        # buzzing more than once.
        for f in findings:
            outcome = notify.push(
                sev="HIGH", code=f.code, project="oauth-rotator", summary=f.message,
                hint="/janitor-credential-window-audit",
            )
            _log(f"notify[{f.code}]: {outcome}")

    # F4 (TRDD-H7NVKSAX → TRDD-4649ZLE0 derived case d): the daemon context that cannot
    # READ the primary live keychain item logged "primary UNREADABLE … using the MIRROR"
    # every minute into rotator.log where nobody looks — a PERSISTENT security
    # degradation only the USER can fix (the keychain ACL re-grant). Probe it here (the
    # read ladder is bounded by safe_storage's run_security timeout + denied-latch, so
    # this cannot wedge the loop) and push it through the human channel. Dedupe makes
    # the standing condition ONE notification, not a drumbeat.
    try:
        import rotator as _rotator  # noqa: PLC0415 -- oauth_rotator sibling, lazy

        _blob, source = _rotator.read_live_blob_with_source()
        if source == "mirror":
            outcome = notify.push(
                sev="HIGH", code="OAUTH-PRIMARY-UNREADABLE", project="oauth-rotator",
                summary=(
                    "the daemon cannot read the PRIMARY live credential (keychain ACL) — "
                    "identity steering degraded to the mirror; a keychain re-grant by the "
                    "user is required"
                ),
                hint="/janitor-refresh-cc-logins",
            )
            _log(f"notify[OAUTH-PRIMARY-UNREADABLE]: {outcome}")
    except Exception:  # noqa: BLE001 -- the probe is best-effort; never break the beat
        pass


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

    RESTART IN THE ORIGINAL TAB WHEREVER POSSIBLE (owner directive 2026-07-29). Rungs 5/6
    already do — they type into the existing pane and create nothing. Before escalating to
    the only rung that opens a new surface, retry with the pane the session RECORDED at
    start (``fleet_restart.recorded_terminal``): live TTY resolution can fail on a pane that
    is perfectly reachable (notably iTerm automation denied by TCC, which
    ``fleet_scan.iterm_automation_blocked`` already detects), and without this retry that
    healthy tab reads as unreachable and rung 7 opens one nobody needed.
    """
    recorded = fleet_restart.recorded_terminal(inst.project_root)
    # MIRROR the original launch line (owner directive 2026-07-29) — resolved HERE, not in
    # the builders, which are pure by contract. A `dead` instance's pid is gone, so this
    # falls through to the argv the session recorded at start; a `frozen` one is still
    # running, so its LIVE argv wins. Preserves every user flag (--model, --add-dir,
    # --mcp-config, a permission mode) instead of guessing a line and silently relaunching
    # a DIFFERENT session.
    command = fleet_restart.relaunch_command(inst.pid, inst.project_root)
    if inst.diagnosis == "dead":
        # `or`: the recorded pane is a FALLBACK, never a substitute — live wins when it
        # resolves, so a moved/recycled pane is still preferred over a stale recording.
        return fleet_restart.build_relaunch(
            inst.terminal, command=command
        ) or fleet_restart.build_relaunch(recorded, command=command)
    plan = fleet_restart.build_force_restart(inst.pid, inst.terminal, command=command)
    if plan is None and recorded:
        plan = fleet_restart.build_force_restart(inst.pid, recorded, command=command)
    if plan is None:
        # The session id is resolved HERE, not inside the builder: `build_*` are pure by
        # contract. A live session makes resurrect open a tmux WINDOW — a TAB under iTerm2's
        # control mode, where a tmux SESSION would instead surface as a whole new WINDOW
        # (owner directive 2026-07-29). "" falls back to a new session, so the rung still
        # always produces a plan.
        plan = fleet_restart.build_resurrect(
            inst.pid,
            inst.project_root,
            session=fleet_restart.live_tmux_session(),
            command=command,
        )
    return plan


def _hard_restart_channel(plan: dict) -> str:
    """The audit-facing channel of a hard-restart plan: relaunch carries it at the
    top level, force_restart nests it under its relaunch sub-plan, resurrect has no
    keystroke channel (it spawns a detached process)."""
    ch = plan.get("channel") or plan.get("relaunch", {}).get("channel")
    return str(ch) if ch else "spawn"


def _run_hard_restart(inst, *, tag, fire, attempts, identity, sf, now, audit, decline) -> None:
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
        # F9: nothing was tried, so back off + audit once (see `_decline`) instead of
        # re-recording this identical decision on every 120 s beat, forever.
        decline("unreachable", "relaunch", None)  # plan is None only on `dead`
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


def task_github_config_audit() -> None:
    """Fleet-wide GitHub-config audit (TRDD-157OH2D7) — the single-writer machine-global sweep.

    The per-session `branch-protection` detector only ever inspects the CURRENT session's
    repo, so a DIFFERENT plugin's repo could be UNPROTECTED (open to stranger PRs/force-pushes)
    or carry `required_linear_history` (which JAMS Claude's merges) and never be seen. This beat
    probes every ai-maestro plugin repo READ-ONLY (rulesets / classic protection / workflows)
    ONCE machine-wide and writes the findings to `<global-state>/github-config-findings.json`,
    which the near-free per-session `fleet-github-config` detector surfaces (that detector makes
    ZERO `gh` calls — all the API cost lives here). The daemon owns it because fleet-scope work
    is the daemon's single-writer job (issue #7): N sessions each probing 13 repos would stampede
    the GitHub API.

    Opt out with CLAUDE_PLUGIN_OPTION_GITHUB_CONFIG_AUDIT_ENABLED=0. A silent no-op when `gh` is
    absent/unauthenticated (every per-repo probe returns indeterminate → zero findings) or the
    marketplace catalog is unreadable (no fleet to audit). NEVER mutates a repo — the on-demand
    /janitor-github-config-fix skill does that.
    """
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_GITHUB_CONFIG_AUDIT_ENABLED", True):
        return
    # Honor the JANITOR_PLUGINS_ROOT test override (same knob state._plugins_root uses), else
    # the real plugins root = the parent of the cache tree the daemon runs from.
    plugins_root = Path(
        os.environ.get("JANITOR_PLUGINS_ROOT", "").strip() or str(_plugins_cache_root().parent)
    )
    audit = gca.audit_fleet(plugins_root, now=int(time.time()))
    # Atomic write (tmp + os.replace) so a per-session reader never sees a half-written file —
    # the file analogue of the single-writer discipline the daemon already enforces for commands.
    out = gs.global_state_dir() / gca.FINDINGS_FILENAME
    tmp = out.with_name(f"{out.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(audit.to_json()), encoding="utf-8")
    os.replace(tmp, out)
    n = len(audit.findings)
    state.log_line(
        "daemon",
        f"github-config audit: {audit.repos_scanned} repos scanned, {n} finding(s)"
        + (f" across {len({f.slug for f in audit.findings})} repo(s)" if n else ""),
    )
    # Human push (TRDD-4649ZLE0 / ARCHITECTURE.md §5): a repo-config gap is exactly the
    # "unattended repo compromised" class the channel exists for — most fleet repos have
    # no live session for weeks. ONE digest line per distinct finding SET (the message
    # embeds `findings_digest`, so notify's content-hash dedupe re-pushes only when the
    # set CHANGES); per-repo detail stays in the per-session `fleet-github-config`
    # surface + /janitor-github-config-fix.
    if n:
        try:
            slugs = sorted({f.slug for f in audit.findings})
            preview = ", ".join(slugs[:3]) + ("…" if len(slugs) > 3 else "")
            digest = gca.findings_digest(audit.to_json())
            outcome = notify.push(
                sev="HIGH", code="GHCFG-FLEET", project=preview or "fleet",
                summary=(
                    f"{n} GitHub-config gap(s) across {len(slugs)} repo(s) "
                    f"[set {digest}] — repos: {preview}"
                ),
                hint="/janitor-github-config-fix",
            )
            state.log_line("daemon", f"  notify[GHCFG-FLEET]: {outcome}")
        except Exception:  # noqa: BLE001 -- the push must never break the audit beat
            pass


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

    # THE TYPING GATE (TRDD-6Q0OYYYH, owner directive 2026-07-18: "the user is present if it
    # was typing in the last 20 seconds"): any keyboard/mouse event within the presence
    # window means a human is AT the machine RIGHT NOW — defer EVERY recovery injection this
    # beat. The per-instance breadcrumbs can't see mid-typing (submit-stamped only), and a
    # human watching a pane get ESC'd/typed-into while they work IS the disturbance this
    # exists to prevent. Deferral is safe: the beat re-runs in ~2 min and a frozen session
    # recovers the moment the human steps away. Fail-open: probe None ⇒ no gate.
    hid = user_intent.hid_idle_seconds()
    if hid is not None and hid <= user_intent.USER_PRESENT_IDLE_S:
        state.log_line(
            "daemon",
            f"session-liveness: user typing (HID idle {hid:.0f}s) — recovery injections deferred this beat",
        )
        return

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

        def _decline(outcome: str, rung: str | None, channel: str | None,
                     *, _inst=inst, _st=st, _sf=sf, _identity=identity) -> None:
            """A decision that TRIED nothing: stamp the cooldown and audit ONCE (F9).

            `attempts`/`last_ts` used to be stamped ONLY on a successful fire, so any
            instance we decide about but cannot poke — no injection channel (a plain
            terminal, VS Code's integrated terminal, an ssh session: neither tmux nor
            iTerm, i.e. a very common setup), an unwired diagnosis, or a dry run — never
            tripped the cooldown. It was re-decided and RE-AUDITED every 120 s beat,
            forever: ~720 identical records/day/instance, which then drove the 1 MB audit
            trim to evict the real fired/force_restart history it exists to preserve, and
            made every append re-read the whole megabyte to hash it. It also broke this
            project's own S3/S4 boundedness invariant ("a self-heal that can run every
            tick MUST dedupe/back-off on an unchanged input").

            So: stamp `last_ts` (never `attempts` — nothing was tried, so no budget is
            spent and the crash-loop gate stays honest), which puts the decision behind
            the normal cooldown; and skip the audit entirely while the (outcome, rung)
            signature is unchanged, so a STEADY unreachable state is recorded once, not
            once per cooldown window."""
            sig = f"{outcome}:{rung or '-'}"
            _write_recovery_state(
                _sf, {**_st, "last_ts": now, "identity": _identity, "last_audit": sig}
            )
            if _st.get("last_audit") != sig:
                _audit(_inst, outcome, rung, channel)

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
            _decline("declined_unwired", action, None)
            continue
        if sl.is_hard_rung(action):
            # A5 hard-restart rungs (TRDD-56d24c02 increment 2). Extracted so the
            # kill-path gates live in ONE reviewed place; executes only behind the
            # DEFAULT-OFF opt-in — else dry-run-logs the built plan.
            _run_hard_restart(
                inst, tag=tag, fire=fire, attempts=attempts,
                identity=identity, sf=sf, now=now, audit=_audit, decline=_decline,
            )
            continue
        # TRDD-8DR0X08A F2 — wedged-target short-circuit. Queued-but-never-executed
        # commands at the transcript tail PROVE typed input is not executing in this
        # pane (a stuck turn: permission dialog / pending question). A SOFT injection
        # would only grow that queue — the exact "janitor keeps printing commands"
        # pile-up the owner reported — so never type again: spend an attempt (the
        # 4-attempt budget must still walk to crash_loop, not loop) and push ONE
        # human notification naming the project. notify's content-hash dedupe + the
        # cooldown keep the push singular. A HARD (ESC-first) rung is exempt: the
        # ESC is the unwedge (same policy _fire_fleet_stop already applies).
        # TRDD-8IZ8COQ8 — the session is parked on a question meant for a HUMAN (an
        # unanswered ExitPlanMode / AskUserQuestion). It looks IDENTICAL to a
        # dead one: a blocked turn appends nothing and cannot fire its cron, so the tests
        # this loop already ran read `cron_dead`. Measured in this repo on 2026-07-17 — an
        # ExitPlanMode call, 33 minutes of silence, then the guardian typed `/janitor-arm`
        # straight into the approval dialog. An unattended machine must never answer a
        # question addressed to a person, so this outranks EVERY rung, hard ones included:
        # an ESC here would DISMISS the human's pending decision, which is the one outcome
        # worse than doing nothing. The wedged check below cannot cover this — its
        # evidence (queued unexecuted commands) only exists once something has ALREADY
        # been typed, so it catches the second injection and never the first.
        if getattr(inst, "awaiting_user", False):
            sig = f"declined_awaiting_user:{action}"
            _write_recovery_state(
                sf,
                {"attempts": attempts + 1, "last_ts": now, "identity": identity,
                 "last_audit": sig},
            )
            state.log_line(
                "daemon",
                f"session-liveness: {tag} AWAITING USER (unanswered tool_use at the "
                f"transcript tail) — would {action}; leaving it for the human",
            )
            if st.get("last_audit") != sig:
                _audit(inst, "declined_awaiting_user", action, None)
            try:
                notify.push(
                    sev="HIGH",
                    code="FLEET-AWAITING-USER",
                    project=os.path.basename(inst.project_root),
                    summary="session is waiting on YOUR answer — it is not stuck",
                    hint="open that project's pane and answer the prompt",
                )
            except Exception:  # noqa: BLE001 -- a notify fault must never break the beat
                pass
            continue
        if getattr(inst, "trailing_enqueues", 0) >= 1 and not fr.injection_is_hard(
            inst.diagnosis
        ):
            sig = f"declined_wedged:{action}"
            _write_recovery_state(
                sf,
                {"attempts": attempts + 1, "last_ts": now, "identity": identity,
                 "last_audit": sig},
            )
            state.log_line(
                "daemon",
                f"session-liveness: {tag} WEDGED ({inst.trailing_enqueues} queued "
                f"unexecuted command(s)) — would {action}; notifying a human instead",
            )
            if st.get("last_audit") != sig:
                _audit(inst, "declined_wedged", action, None)
            try:
                notify.push(
                    sev="HIGH",
                    code="FLEET-WEDGED",
                    project=os.path.basename(inst.project_root),
                    summary="session wedged mid-turn — typed commands queue but never run",
                    hint="open that project's pane and answer the pending dialog",
                )
            except Exception:  # noqa: BLE001 -- a notify fault must never break the beat
                pass
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
            _decline("unreachable", action, None)
            continue
        if not fire:
            state.log_line(
                "daemon", f"session-liveness:DRY would {action} → {plan['channel']} for {tag}"
            )
            _decline("dry_run", action, str(plan["channel"]))
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

    # The FREE half of the rate-limit recovery (TRDD-X07E7HTN, D1 v1). Same scanned fleet,
    # same beat — so it inherits the SESSION_LIVENESS_ENABLED gate above AND the typing gate
    # (the whole beat already returned if the user is at the keyboard). DEFAULT-OFF.
    _resume_wake_pass(fleet, now, fire=fire)


# Daemon-owned rate-limit RESUME wake (TRDD-X07E7HTN, D1 v1) — env knob + window key.
_RATELIMIT_WAKE_ENABLED_ENV = "CLAUDE_PLUGIN_OPTION_DAEMON_RATELIMIT_WAKE_ENABLED"


def _rate_limit_window_key(sd: Path, flag: Path) -> int:
    """A STABLE per-rate-limit-window key for the resume-wake dedupe (TRDD-X07E7HTN).

    Prefer `rate-limited-since.ts` (written by on-stop-failure alongside the flag); fall back
    to the flag's own mtime when the since-file is absent/0 (clock skew). A NEW limit writes a
    NEW value → a new window → a legitimately-repeated resume is NOT swallowed. Returns 0 only
    when neither is readable — the caller treats that as "cannot key this window" and stamps
    nothing (fail-open toward the cron fallback)."""
    since = state.read_int_state(sd / state.RATE_LIMITED_SINCE_FILE, 0)
    if since > 0:
        return since
    try:
        return int(flag.stat().st_mtime)
    except OSError:
        return 0


def _resume_wake_pass(fleet: list, now: int, *, fire: bool) -> None:
    """Daemon-owned rate-limit RESUME wake (TRDD-X07E7HTN, D1 v1) — the FREE half of the
    rate-limit recovery, so an injectable rate-limited session's cron can leave the paid
    FAST poll.

    The FAST `*/5` cron a rate-limited session sits in exists only to catch the moment the
    API clears and emit [janitor-resume] — dozens of ~$0.76 quiet model turns across a
    multi-hour limit. This pass does that half with NO model attached: for every non-frozen,
    injectable, rate-limited instance it types the `/janitor-resume` SLASH COMMAND (soft
    enqueue) into the pane and stamps `daemon-wake-covered.ts`, so that session's cron may
    demote off FAST (the arm handshake, MF4). The cron stays armed as the fail-open fallback,
    and the single-consumer `rate-limited.flag` (only dispatch clears it) means the daemon
    inject and a cron fire can never double-resume — whichever runs `/janitor-resume` first
    clears the flag; the other no-ops.

    DEFAULT-OFF (`CLAUDE_PLUGIN_OPTION_DAEMON_RATELIMIT_WAKE_ENABLED`): until opted in the
    cron is the only trigger, exactly as today. Fail-open throughout.

    MF1 — reconciled with esc_nudge: a `frozen` pane is handled ONLY by the recovery loop's
    ESC-only esc_nudge (typing a command into a frozen pane buffers on the retry-blocked input
    line and floods, TRDD-P7WU40G9). This pass therefore targets ONLY `healthy` instances —
    the one non-frozen state a rate-limited pane reaches (`server_owned`/`unarmed`/`dead` are
    hands-off; `version_mismatch`/`cron_dead` are owned by the recovery loop above and never
    coincide with a rate-limit flag) — so it can never double-actuate an instance the recovery
    loop is already driving, and it fires only once the diagnosis has flipped off `frozen`.
    MF2 — actuation is the `/janitor-resume` COMMAND, never the bare [janitor-resume] marker
    (a typed marker is defanged content — dispatch._defang_foreign_markers). The command turn
    is self-verifying for reachability (it completes only when the API is reachable).
    MF3 — the wake-dedupe + coverage-stamp writes take the per-project `detector.lock`; this
    pass runs NO detector and touches NO `last-run-*.ts` / seen-file, so no dedupe can corrupt.
    """
    if not state.is_truthy_env(_RATELIMIT_WAKE_ENABLED_ENV, False):
        return
    for inst in fleet:
        root = inst.project_root
        if not root:
            continue
        # ONLY `healthy` — see MF1 in the docstring. Excludes frozen (esc_nudge owns it),
        # server_owned/unarmed/dead (hands-off), and version_mismatch/cron_dead (recovery-loop
        # owned + never rate-limited). This is the disjointness guarantee with the loop above.
        if inst.diagnosis != "healthy":
            continue
        sd = Path(root) / ".janitor" / "state"
        flag = sd / state.RATE_LIMITED_FLAG
        if not flag.is_file():
            continue  # not rate-limited → nothing to wake
        # A queued-but-unexecuted command at the pane's tail means a soft inject would only
        # pile up (the "janitor keeps printing commands" wedge, TRDD-8DR0X08A). Skip entirely —
        # NO coverage stamp — so dispatch keeps FAST and the cron stays the trigger.
        if getattr(inst, "trailing_enqueues", 0) >= 1:
            continue
        # Parked on a HUMAN decision (TRDD-8IZ8COQ8) — same reasoning as the recovery
        # beat: a rate-limited session that is ALSO holding an approval dialog must not be
        # typed into. No coverage stamp, so dispatch keeps FAST and the cron stays the
        # trigger; the human answering the prompt is what unblocks it.
        if getattr(inst, "awaiting_user", False):
            continue
        # Build the resume injection (soft enqueue). None ⇒ un-injectable pane (plain / VS Code
        # / ssh — no resolvable terminal): we CANNOT prove a wake, so stamp NO coverage and
        # dispatch keeps this session FAST (MF4 fail-open — the cron is its only trigger).
        plan = fleet_inject.build_injection(inst.terminal, "resume", esc_first=False)
        if plan is None:
            continue
        with gs.detector_lock(sd) as held:
            if not held:
                continue  # the cron (or a concurrent beat) holds this project's writer lock
            since = _rate_limit_window_key(sd, flag)
            if since <= 0:
                continue  # cannot key this window (no since, unreadable mtime) — fail-open
            dedupe = sd / state.DAEMON_RESUME_WAKE_FILE
            covered = sd / state.DAEMON_WAKE_COVERED_FILE
            label = os.path.basename(root)
            if state.read_int_state(dedupe, 0) != since:
                # A NEW rate-limit window (or the first inject) — deliver ONE /janitor-resume.
                if not fire:
                    state.log_line(
                        "daemon",
                        f"resume-wake:DRY would /janitor-resume → {plan['channel']} for {label}",
                    )
                    continue
                if fleet_inject.fire(plan):
                    state.atomic_write(dedupe, str(since))  # dedupe: injected for THIS window
                    state.atomic_write(covered, str(now))   # coverage PROVEN → dispatch may demote
                    state.log_line(
                        "daemon", f"resume-wake: FIRED /janitor-resume → {plan['channel']} for {label}"
                    )
                else:
                    state.log_line("daemon", f"resume-wake: FIRE-FAILED /janitor-resume for {label}")
            else:
                # Already injected /janitor-resume for THIS window; the enqueued command is the
                # armed wake. Re-stamp coverage EVERY beat so the session's cron stays demoted
                # while the daemon keeps covering it (dispatch requires a FRESH stamp). Overwrite,
                # not append — the file just holds the latest ts, so it stays bounded (S3/S4).
                state.atomic_write(covered, str(now))


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
    sessions = [
        {
            "pid": i.pid,
            "command": i.command,
            "terminal": i.terminal,
            # Harness agents a live server owns get their global control from the
            # SERVER, never from this daemon's injection (TRDD-PZLVT2RN).
            "server_owned": i.diagnosis == "server_owned",
            # F2 delivery honesty: the selector refuses to enqueue a stop at a
            # frozen session (a stalled queue never delivers it) — see fleet_stop.
            "diagnosis": i.diagnosis,
        }
        for i in fleet
    ]
    # THE TYPING GATE (TRDD-6Q0OYYYH): while the human is at the keyboard (any HID event
    # within the presence window) EVERY session counts user-active — the stop-flag is held,
    # so deferring costs nothing (the next beat injects once they step away), while typing
    # a stop command under a working human is exactly the disturbance the owner banned.
    hid = user_intent.hid_idle_seconds()
    typing_now = hid is not None and hid <= user_intent.USER_PRESENT_IDLE_S
    plans = fleet_stop.select_stop_targets(
        sessions,
        flag_state=flag_state,
        self_pid=os.getpid(),
        daemon_pid=gs.daemon_pid(),
        already_injected=gs.fleet_injections_seen(),
        user_active_pids={i.pid for i in fleet} if typing_now
        else {i.pid for i in fleet if i.active},
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

    def __init__(
        self, name: str, interval_s: int, fn: Callable[[], None], *, background: bool = False
    ) -> None:
        self.name = name
        self.interval_s = interval_s
        self.fn = fn
        # Background tasks run in ONE detached child at a time (the "bulk lane") so a
        # 20-minute bulk workload can never block the main loop's 60 s survival beats.
        # WHY: oauth-rotation starvation incident 2026-07-17 — two back-to-back ~1190 s
        # marketplace-refresh runs blinded the loop while an account hit its 5 h wall;
        # rotation that should have fired at ~15:46 never ran and the user had to
        # switch accounts by hand.
        self.background = background
        self._child: Optional[subprocess.Popen[bytes]] = None
        self._child_t0 = 0.0
        # WRITE to the fixed control plane (TRDD-QK7M2B0X phase B step 2): the completion
        # stamp is what a live ai-maestro server reads to see whether a chore is already
        # covered, so it must sit at a path a foreign process can stat literally.
        self.last_run_path = gs.last_run_path(name)
        # Consecutive-failure streak (Pillar 1) deliberately does NOT move: it is private
        # daemon state — no second owner acts on it — and the scope rule is AUDIENCE, not
        # kind. Moving it would widen the control plane for nothing.
        self.failcount_path = gs.global_state_dir() / f"{name}.failcount"

    def _last_run(self) -> int:
        # Dual-read (NEWEST wins), not a plain read of `last_run_path`: during the upgrade
        # window a previous-release daemon still stamps global_state_dir(), and reading
        # only the new path would see 0 == "never ran" and re-run the chore immediately.
        return gs.read_last_run(self.name)

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
        if self._child is not None:
            # An unreaped background run is in flight: never "due" (a due task would be
            # respawned every loop) and never 0 (a 0 would clamp the main-loop sleep to
            # 1 s and busy-spin for the whole bulk run). Re-evaluated after the reap.
            return _BULK_RECHECK_SEC
        penalty = self._backoff_penalty(self._failcount())
        return max(0, self._last_run() + self.interval_s + penalty - int(time.time()))

    def is_due(self) -> bool:
        return self.time_until_due() == 0

    def child_alive(self) -> bool:
        """True iff this task's detached background child is still running."""
        return self._child is not None and self._child.poll() is None

    def spawn_background(self) -> None:
        """Start this task's fn in a DETACHED child (`daemon.py --run-task <name>`).

        The parent stamps last-run/failcount when the child is REAPED
        (`poll_background`), mirroring the foreground bookkeeping. A spawn failure is
        recorded as a failed run so the task retries on cadence, not every loop."""
        try:
            self._child = subprocess.Popen(
                [sys.executable, os.path.abspath(__file__), "--run-task", self.name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,  # own pgroup → killpg reaps its subprocesses too
            )
            self._child_t0 = time.time()
            state.log_line(
                "daemon", f"task '{self.name}' starting (background pid {self._child.pid})"
            )
        except Exception as exc:  # noqa: BLE001 - a spawn failure must not kill the loop
            self._child = None
            state.atomic_write(self.last_run_path, str(int(time.time())))
            state.atomic_write(self.failcount_path, str(self._failcount() + 1))
            state.log_line("daemon", f"task '{self.name}' background spawn FAILED: {exc}")

    @staticmethod
    def _notify_quarantine(name: str, fails: int) -> None:
        """Human push (TRDD-4649ZLE0 derived case a): a daemon task ENTERING quarantine
        is a machine-level failure only a human can investigate, and the daemon has no
        project session to surface it into. Fires exactly ONCE per failure streak (at
        the quarantine threshold, not on every failure — later failures change the
        message text, which would defeat notify's content-hash dedupe and buzz until
        the daily cap). Best-effort, never breaks the reap/run path."""
        if fails != _TASK_BACKOFF_AFTER_FAILS:
            return
        try:
            outcome = notify.push(
                sev="HIGH", code="TASK-QUARANTINE", project="janitor-daemon",
                summary=(
                    f"daemon task '{name}' failed {fails}x consecutively and entered "
                    f"quarantine (exponential backoff) — inspect daemon.log"
                ),
                hint="/janitor-show-global-status",
            )
            state.log_line("daemon", f"  notify[TASK-QUARANTINE:{name}]: {outcome}")
        except Exception:  # noqa: BLE001 -- the push must never break task bookkeeping
            pass

    def poll_background(self) -> None:
        """Reap a finished detached child: stamp last-run + failcount exactly as a
        foreground run would. No-op while it is still running or when none exists.
        A child running past the workload cap (+grace) is hard-killed — its own
        internal `_run_workload` caps should have ended it, so past that it is wedged."""
        if self._child is None:
            return
        rc = self._child.poll()
        if rc is None:
            if time.time() - self._child_t0 > _WORKLOAD_TIMEOUT_SEC + _BULK_CHILD_KILL_GRACE_SEC:
                try:
                    os.killpg(self._child.pid, signal.SIGKILL)
                except Exception:  # noqa: BLE001 - pgroup may already be gone
                    with contextlib.suppress(Exception):
                        self._child.kill()
                state.log_line(
                    "daemon",
                    f"task '{self.name}' background child pid {self._child.pid} "
                    f"exceeded the workload cap — killed",
                )
            return
        dt_s = int(time.time() - self._child_t0)
        self._child = None
        state.atomic_write(self.last_run_path, str(int(time.time())))
        if rc != 0:
            fails = self._failcount() + 1
            state.atomic_write(self.failcount_path, str(fails))
            penalty = self._backoff_penalty(fails)
            note = f" — quarantined, next run +{penalty}s" if penalty else ""
            state.log_line(
                "daemon",
                f"task '{self.name}' FAILED in {dt_s}s (background rc={rc}, "
                f"consecutive={fails}){note}",
            )
            self._notify_quarantine(self.name, fails)
        else:
            if self._failcount():
                state.atomic_write(self.failcount_path, "0")
            state.log_line("daemon", f"task '{self.name}' done in {dt_s}s (background)")

    def run(self) -> None:
        if self.child_alive():
            # Belt for the cadence-bypass callers (_consume_version_update_request):
            # a synchronous run while this task's background child is in flight would
            # double-run the chore the background lane exists to serialize.
            state.log_line(
                "daemon", f"task '{self.name}' skipped — background run already in flight"
            )
            return
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
                self._notify_quarantine(self.name, fails)
            else:
                if self._failcount():
                    state.atomic_write(self.failcount_path, "0")  # recovered → reset the streak
                state.log_line("daemon", f"task '{self.name}' done in {dt}s")


def _build_tasks() -> list[Task]:
    # background=True marks the BULK chores (long network/CLI sweeps — a
    # marketplace refresh alone runs ~20 min at low priority). They execute in one
    # detached child at a time (the bulk lane), so the 60 s survival beats below
    # (oauth-rotator-tick above all) are never starved behind them — the
    # oauth-rotation starvation incident, 2026-07-17. One lane (not N children)
    # preserves the old single-loop serialization between the bulk chores
    # themselves; the cross-process file locks stay as the backstop.
    return [
        Task("marketplace-refresh", _INTERVAL_MARKETPLACE_REFRESH, task_marketplace_refresh,
             background=True),
        Task("user-plugins-update", _INTERVAL_USER_PLUGINS_UPDATE, task_user_plugins_update,
             background=True),
        Task("version-update", _INTERVAL_VERSION_UPDATE, task_version_update,
             background=True),
        Task("oauth-rotator-supervisor", _INTERVAL_OAUTH_SUPERVISOR,
             task_oauth_rotator_supervisor),
        Task("oauth-rotator-tick", _INTERVAL_OAUTH_TICK, task_oauth_rotator_tick),
        Task("memory-guard", _INTERVAL_MEMORY_GUARD, task_memory_guard),
        Task("cache-prune", _INTERVAL_CACHE_PRUNE, task_cache_prune),
        Task("rules-cleanup", _INTERVAL_RULES_CLEANUP, task_rules_cleanup),
        Task("github-config-audit", _INTERVAL_GITHUB_CONFIG_AUDIT, task_github_config_audit,
             background=True),
        Task("session-liveness", _INTERVAL_SESSION_LIVENESS, task_session_liveness),
        Task("fleet-stop", _INTERVAL_FLEET_STOP, task_fleet_stop),
    ]


# Machine-wide ONCE-ONLY chores the ai-maestro SERVER absorbs while it RUNS
# (TRDD-PZLVT2RN Phase B2; BINARY since TRDD-LU0C5KAR — owner directive 2026-07-17:
# "if the ai-maestro server is running, those chores are its responsibility. so the
# janitor daemon must switch off those chores. any other event is a bug"). Server
# alive ⇒ every task in this set yields; server gone ⇒ they all run. Everything NOT
# in the set keeps running regardless: the population-split ops (session-liveness,
# fleet-stop — each side actuates only its own population, enforced per-instance via
# the `server_owned` diagnosis) and the janitor-only Family-B chores (memory-guard,
# cache-prune, rules-cleanup, github-config-audit). The set is the SSOT in
# harness_backend.
#
# PORT NOTE (ordering — read main() alongside this): a REAL fresh server-liveness file
# triggers the ONE-DAEMON-PER-HOST binary EXIT in main() (the `server_is_alive()` break,
# TRDD-5ZVS1DDP) BEFORE this per-chore yield is ever evaluated — so with a genuine live
# server the daemon STOPS ENTIRELY and even the Family-B chores pause (the "keeps running
# regardless" clause above holds only when the daemon is still looping). This absorbed-set
# yield therefore governs the SECONDARY cases only: the env-override path
# (`server_runs_chores()` forced True via JANITOR_AIMAESTRO_SERVER_CHORES without a
# live-file exit) and the maintenance keepalive. In normal operation without that override,
# `server_runs_chores() == server_is_alive()`, so the break at line 2150 wins and this
# yield yields nothing.
_SERVER_ABSORBED_TASK_NAMES = harness_backend.SERVER_ABSORBED_TASKS


def _task_yielded_to_server(task_name: str, server_runs_chores: bool) -> bool:
    """PURE: must the daemon yield `task_name` to the active ai-maestro server?
    Binary (TRDD-LU0C5KAR): an absorbed chore yields IFF the server is alive —
    responsibility follows process liveness, never per-chore capability."""
    return server_runs_chores and task_name in _SERVER_ABSORBED_TASK_NAMES


def _yielded_task_names(tasks: list[Task], server_runs_chores: bool) -> set[str]:
    """The names in `tasks` yielded to the server for this loop iteration. A yielded
    task must be excluded from BOTH the due-loop AND the next-due sleep computation —
    a due-but-yielded task left in `time_until_due` would clamp the sleep to ~1 s and
    busy-spin the daemon for as long as the server stays up."""
    return {t.name for t in tasks if _task_yielded_to_server(t.name, server_runs_chores)}


def _next_bulk_task(tasks: list[Task], yielded: set[str]) -> Task | None:
    """The due background task that gets the single bulk lane this pass — the
    LEAST-RECENTLY-RUN one, NOT the first in list order.

    Fixed list order starves. Every bulk task reads last-run 0 on a fresh state dir,
    so all four are due at once and the head of the list takes the lane on every
    pass. It then re-stamps its own last-run, and if its cadence is shorter than its
    runtime plus the reap beat it is due AGAIN by the time the lane frees — so the
    tasks queued behind it never run at all. That is the same starvation the bulk
    lane itself was built to cure (oauth-rotation incident, 2026-07-17), one level
    down: the lane stopped the bulk chores starving the 60 s survival beats, but
    nothing stopped a bulk chore starving its bulk siblings.

    It is not only a test artifact. In production `marketplace-refresh` heads the
    list at a 3600 s cadence and runs ~20 min, so it normally yields the lane — but
    a refresh that stalls past its own cadence (a slow network is exactly what the
    1800 s workload cap exists for) makes it perpetually due, and `version-update`
    and `github-config-audit` then never run again while it keeps stalling.

    Oldest-last-run-first is starvation-free by construction: a task that just ran
    sorts last, so every due task reaches the lane within one round regardless of
    cadence. Ties — notably the all-zero fresh-install case — fall back to list
    order, which is `min`'s documented first-minimal-wins stability."""
    due = [t for t in tasks if t.background and t.name not in yielded and t.is_due()]
    return min(due, key=lambda t: t._last_run()) if due else None


def _run_due_tasks(tasks: list[Task], yielded: set[str]) -> bool:
    """One due-pass over `tasks` (extracted from main() for testability after the
    2026-07-17 oauth-rotation starvation incident).

    Foreground tasks run synchronously as before. Background (bulk) tasks run in ONE
    detached child at a time — the bulk lane: finished children are reaped first
    (stamping last-run/failcount), then at most one due background task is spawned.
    One lane (not N children) preserves the old single-loop serialization between
    the bulk chores themselves. A due background task deferred by a busy lane stays
    due and is retried on the next pass. Returns whether the bulk lane is busy AFTER
    the pass, for the sleep computation."""
    for task in tasks:
        if task.background:
            task.poll_background()  # reap even while yielded/paused — bookkeeping only
    bulk_busy = any(t.child_alive() for t in tasks if t.background)
    # Decided ONCE, before the loop, so the choice cannot depend on where we are in
    # list order — that dependence is exactly the starvation `_next_bulk_task` cures.
    bulk_next = None if bulk_busy else _next_bulk_task(tasks, yielded)
    for task in tasks:
        # A kill-switch set mid-loop skips the REMAINING tasks NOW, not after the current
        # (up to 1800s) task finishes — TRDD-ME8V2YJF component B. Pause and maintenance
        # used to join it here; both are gone (owner directive 2026-07-31), so the only
        # thing that stops the chores is the stop that also stops the daemon.
        if not _running or gs.kill_switch_present():
            break
        if task.name in yielded:
            continue  # the active server owns this chore (Phase B2)
        if not task.is_due():  # a task with a live child is never due (time_until_due)
            continue
        if task.background:
            if bulk_busy or task is not bulk_next:
                continue  # one bulk lane: defer; the task stays due for the next pass
            task.spawn_background()
            bulk_busy = True
            continue
        task.run()
    return any(t.child_alive() for t in tasks if t.background)


def _sleep_seconds(tasks: list[Task], yielded: set[str], bulk_busy: bool) -> int:
    """Seconds the main loop should sleep before the next due-pass.

    Yielded tasks are excluded — a due-but-yielded task would report
    time_until_due()==0 and clamp the sleep to 1 s, a busy-spin for as long as the
    server stays up (Phase B2). A due background task deferred by a busy bulk lane
    contributes the recheck beat instead of 0 for the same reason."""

    def contribution(t: Task) -> int:
        ttd = t.time_until_due()
        if t.background and bulk_busy and ttd == 0:
            return _BULK_RECHECK_SEC
        return ttd

    next_due = min(
        (contribution(t) for t in tasks if t.name not in yielded),
        default=_LOOP_CEILING_SEC,
    )
    return max(1, min(_LOOP_CEILING_SEC, next_due))


def _report_foreign_era_daemon(self_pid: int, reported: set[int]) -> None:
    """Detect a SECOND daemon publishing itself at another era's path (TRDD-QK7M2B0X).

    `acquire_singleton_dual` is supposed to make this impossible — it holds every era's
    inode, so a peer of either era must lose. But "impossible by construction" is a claim,
    and an unverified claim about a singleton is exactly how the last two-daemon bug stayed
    hidden: `daemon.heartbeat.ts` kept advancing, so the host looked healthy while two
    processes ran the same chores. This costs one stat plus one `kill(pid, 0)` per era per
    tick and turns that silence into an indexed HIGH finding.

    `reported` is the caller's per-process dedupe set: the condition persists across every
    tick, and an append-only ledger growing by a line per tick is its own outage.
    """
    try:
        foreign = gs.foreign_era_daemons(self_pid)
    except Exception as exc:  # noqa: BLE001 — a diagnostic must never stop the loop
        state.log_line("daemon", f"foreign-era daemon check skipped: {exc}")
        return
    for era, pid in foreign:
        if pid in reported:
            continue
        reported.add(pid)
        msg = f"second daemon detected: pid {pid} published at the {era} era path (this daemon is {self_pid})"
        state.log_line("daemon", msg)
        try:
            findings_ledger.record(sev="HIGH", code="DAEMON-DOUBLE", src="daemon", msg=msg)
        except Exception as exc:  # noqa: BLE001 — an unfilable finding must not stop the loop
            state.log_line("daemon", f"DAEMON-DOUBLE ledger write failed: {exc}")


def _consume_version_update_request(tasks: list[Task]) -> bool:
    """Release-triggered self-update consume (TRDD-Y9KM5RCJ).

    If a session `version-update` detector raised the request flag (the plugin cache is
    behind the latest GitHub release), CLEAR it first — clear-before-run: a run that
    fails is re-signalled by the detector's next ~5 min fire, so a crash after a
    clear-after-run can never strand the request — then run the version-update Task
    exactly once via its `.run()` wrapper. Going through the Task (not a bare
    `task_version_update()` call) FORCES the run past the 6 h cadence yet keeps the
    normal bookkeeping: the last-run stamp resets the 6 h clock and the failcount/backoff
    supervision still applies. The detector only re-requests while genuinely behind, so on
    a successful update the requests stop (self-terminating); a persistently-failing update
    retries at most at the detector's ~5 min cadence (the flag is cleared here and only
    re-set on the detector's next fire), never every loop. Returns True iff a request was
    consumed. Called from the main loop AFTER the stop/pause/maintenance branches — a
    stopped or idled daemon must never self-update."""
    if not gs.version_update_requested_present():
        return False
    gs.clear_version_update_request()
    for task in tasks:
        if task.name == "version-update":
            task.run()
            break
    return True


def _consume_plugin_update_requests() -> int:
    """Universal per-plugin update consume (TRDD-YMTUPQER) — the single-writer half.

    The per-session `plugin-updates` detector cannot run `claude plugin update --scope user`
    itself (N sessions would stampede — issue #7 / PRRD S2.1), so it ENQUEUES a request; this
    consumes each one here (the daemon is the sole user-scope writer). For each queued request:
    clear-before-run (a run that fails is re-signalled by the detector's next ~5 min fire, so a
    daemon crash mid-run never strands it), then — DEFENSE-IN-DEPTH: `is_ai_maestro_plugin_id`
    excludes BOTH the janitor self (Y9KM5RCJ owns its own update) and every ai-maestro fleet
    plugin (fleet-skew lockstep — the USER decision) — run `claude plugin marketplace update
    <mkt>` + `claude plugin update <id> --scope user` under the shared marketplace lock. On a
    real version change, stamp the reload generation so the target's session picks it up.
    Returns the count actually updated. Called from the main loop AFTER the
    stop/pause/maintenance branches — a stopped or idled daemon must never act."""
    reqs = gs.plugin_update_requests()
    if not reqs:
        return 0
    updated = 0
    for req in reqs:
        plugin_id = str(req.get("plugin_id") or "")
        scope = str(req.get("scope") or "")
        gs.clear_plugin_update_request(plugin_id, scope)  # clear-before-run
        if "@" not in plugin_id or scope != "user":
            continue
        if state.is_ai_maestro_plugin_id(plugin_id):
            state.log_line("daemon", f"plugin-update: skipping self/fleet plugin {plugin_id}")
            continue
        marketplace = plugin_id.split("@", 1)[1]
        with gs.marketplace_lock() as got:
            if not got:
                # Contention (not failure) — re-enqueue so a later loop retries without
                # waiting for the detector's ~5 min re-signal.
                gs.request_plugin_update(plugin_id, scope, str(req.get("reason") or ""))
                state.log_line("daemon", f"plugin-update deferred (marketplace lock held): {plugin_id}")
                continue
            try:
                subprocess.run(  # noqa: S603 - explicit args, no shell
                    ["claude", "plugin", "marketplace", "update", marketplace],
                    capture_output=True, text=True, timeout=120, check=False,
                )
                up = subprocess.run(  # noqa: S603
                    ["claude", "plugin", "update", plugin_id, "--scope", "user"],
                    capture_output=True, text=True, timeout=180, check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                state.log_line("daemon", f"plugin-update {plugin_id} failed: {exc}")
                continue
        # Share the ROBUST matcher with the other two update paths in this file (audit
        # finding 4). A bare `"updated from"` substring made any CLI wording change —
        # "Updated from", "updated to vX", an arrow form, localized output — a false
        # negative: the plugin IS updated on disk, but no reload generation is stamped, so
        # every live session keeps running the OLD cached code until some other path
        # happens to set the flag.
        if up.returncode == 0 and _stdout_proves_plugin_updated(up.stdout or ""):
            gs.set_reload_flag(f"plugin-update@{plugin_id}")
            state.log_line("daemon", f"plugin-update: updated {plugin_id} [scope=user]; reload flag set")
            updated += 1
        else:
            state.log_line("daemon", f"plugin-update {plugin_id}: no change (rc={up.returncode})")
    return updated


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
    # Dual-era (TRDD-QK7M2B0X phase B step 2): the singleton is held on control_dir()'s
    # daemon.flock AND the old global_state_dir() one for the transition window. A 0.6x
    # daemon knows only the old inode, and flock(2) excludes only processes contending on
    # the SAME file — so holding just the new path would let both eras believe they are the
    # machine's single writer, which is the two-daemon condition §7.2 exists to prevent.
    flock_handle = gs.acquire_singleton_dual(blocking=_KEEPALIVE_INSTANCE)
    if flock_handle is None:
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
    foreign_daemons_reported: set[int] = set()  # per-process dedupe for DAEMON-DOUBLE
    chores_yielded_last_loop = False  # Phase B2 transition logging (yield ↔ resume), not per-tick spam
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

            # ONE DAEMON PER HOST (TRDD-5ZVS1DDP, ARCHITECTURE §7.2; owner 2026-07-21:
            # "only one daemon can exist at the same time in the host ... otherwise they
            # will conflict and write at the same time in the same files, corrupting
            # them"). A FRESH ai-maestro server-liveness file means a server owns this
            # host, so we get out of its way ENTIRELY — not the rev-4 per-chore yield,
            # which left us running and contending on the same state.
            #
            # Checked SECOND, right after the kill-switch: a deliberate human stop still
            # outranks it, but this must precede maintenance/pause so we never sit
            # "idling" alongside a live server — idling still holds the singleton flock
            # and keeps the OS keepalive armed, which is exactly the two-owner condition.
            #
            # Detection is by FILE only. The server is "wherever the user installs
            # ai-maestro" and runs under pm2, so we can neither locate nor stop it; the
            # liveness file is the whole handshake.
            if harness_backend.server_is_alive():
                exit_reason = "server-owns-host"
                break

            # The global-MAINTENANCE and global-PAUSE branches stood here. Both idled the
            # daemon without tearing it down — every task workload skipped, heartbeat still
            # ticking so nobody saw us as wedged, sessions still firing on schedule. That
            # combination is precisely what made the silent-disable incident invisible
            # (owner directive 2026-07-31), so both flags and both branches are gone. A
            # machine-wide stop is now the kill-switch alone, which EXITS and is therefore
            # observable. Cost is answered by each session's cadence tier, which slows the
            # fires without stopping the work.

            # Phase B2 (TRDD-PZLVT2RN): while an ACTIVE ai-maestro server RUNS, yield
            # the absorbed chores — running them here too would be "doing the same
            # chores twice". BINARY since TRDD-LU0C5KAR (owner directive 2026-07-17):
            # a running server owns them ALL; its exit (the probe file goes stale
            # within 90 s) hands them ALL back. Resolved once per loop iteration.
            server_chores = harness_backend.server_runs_chores()
            yielded = _yielded_task_names(tasks, server_chores)
            if bool(yielded) != chores_yielded_last_loop:  # log transitions, not every tick
                chores_yielded_last_loop = bool(yielded)
                state.log_line(
                    "daemon",
                    (
                        f"chore-coordination: yielding to active ai-maestro server: {sorted(yielded)}"
                        if yielded
                        else "chore-coordination: server no longer confirmed active — resuming singleton chores"
                    ),
                )

            # The consume paths are cadence-bypass entrances to two absorbed tasks, so each
            # gates on ITS OWN task being yielded (not on "anything yielded" — that would
            # over-suppress if the absorbed set ever narrows). While the server owns the
            # update chores the requests stay QUEUED, not consumed — so the moment the
            # server drops, the takeover starts from the pending queue.
            if "version-update" not in yielded:
                # Release-triggered self-update (TRDD-Y9KM5RCJ): consume any pending request
                # from a session detector and run the janitor self-update NOW (≤ ~60 s) instead
                # of on the 6 h version-update beat. Placed AFTER the stop/pause/maintenance
                # branches above (each of which `break`s or `continue`s, so reaching here means
                # the daemon is actively working) and BEFORE the due-loop.
                _consume_version_update_request(tasks)
            if "user-plugins-update" not in yielded:
                # Universal per-plugin update (TRDD-YMTUPQER): consume USER-scope update requests
                # the plugin-updates detector enqueued and run them as the single writer (#7).
                _consume_plugin_update_requests()

            bulk_busy = _run_due_tasks(tasks, yielded)

            gs.write_heartbeat()

            # Verify the singleton actually held, every tick. Placed right after the beat
            # because the beat is what made the last two-daemon incident invisible: it kept
            # advancing while two processes ran the same chores, so "the daemon looks alive"
            # was true and useless. Cheap, fail-open, deduped per process.
            _report_foreign_era_daemon(pid, foreign_daemons_reported)

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
            # increments so signals interrupt promptly. Yield + bulk-lane deferral
            # exclusions live in _sleep_seconds (Phase B2; bulk-lane incident).
            sleep_for = _sleep_seconds(tasks, yielded, bulk_busy)
            for _ in range(sleep_for):
                if not _running or gs.kill_switch_present():
                    break
                time.sleep(1)
    finally:
        if exit_reason in ("kill-switch", "server-owns-host"):
            # Both are DELIBERATE stops, so the OS keepalive must go — launchd
            # `KeepAlive: true` / `ThrottleInterval: 30` and systemd `Restart=always`
            # would otherwise relaunch us within 30 s, forever. For the kill-switch that
            # fights the user's explicit disarm; for server-owns-host it would produce a
            # permanent spawn→exit thrash AGAINST a live server, i.e. the two-owner
            # condition §7.2 exists to prevent, plus a log full of 30-second restarts.
            #
            # Dropping the keepalive is safe because it is NOT our resurrection path: the
            # per-session heartbeat calls `ensure_daemon_running()` every fire, so once
            # the server's liveness goes stale (≤90 s) the next heartbeat spawns a fresh
            # daemon, which re-installs the keepalive on startup. NOT done on a plain
            # signal/self-update exit, where an immediate respawn is exactly what we want.
            _uninstall_os_keepalive()
        state.log_line("daemon", f"stopping ({exit_reason})")
        gs.remove_daemon_pid()
        gs.release_singleton_dual(flock_handle)
        state.rotate_log_if_big("daemon")

    return 0


def _run_task_child(name: str) -> int:
    """`daemon.py --run-task <name>` — the detached background-lane child.

    Runs ONE task's fn to completion and exits; the PARENT daemon does all the
    bookkeeping (last-run stamp, failcount) from the observed exit code, so this
    deliberately calls `task.fn()` and NOT `task.run()`. No singleton flock, no pid
    file, no signal handlers — this is a worker, not a daemon. The cross-process
    file locks inside the fns (marketplace_lock etc.) remain the collision backstop.
    `noop` (and any `noop-*`) exits 0 without touching anything — the smoke-test of
    the child-exec path (also what the background-lane tests spawn so no real
    workload ever runs; the `noop-*` prefix lets tests use DISTINCT task names,
    since cadence stamps are keyed by name)."""
    if name == "noop" or name.startswith("noop-"):
        return 0
    for task in _build_tasks():
        if task.name == name:
            try:
                task.fn()
            except Exception as exc:  # noqa: BLE001 - the rc IS the report channel
                state.log_line("daemon", f"task '{name}' (background child) raised: {exc}")
                return 1
            return 0
    state.log_line("daemon", f"--run-task: unknown task '{name}'")
    return 3


if __name__ == "__main__":
    if "--run-task" in sys.argv:
        idx = sys.argv.index("--run-task")
        sys.exit(_run_task_child(sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""))
    sys.exit(main())
