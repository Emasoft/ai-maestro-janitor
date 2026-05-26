# Shared contract for the GLOBAL janitor daemon — system-wide singleton that
# owns every auto-update operation touching machine-global state.
#
# Background: per-project PID dedup cannot prevent concurrent
# `claude plugin marketplace update` and `claude plugin update --scope user`
# pile-up across multiple Claude Code sessions, because the work is global
# while the gate was per-project. Detailed report: GitHub issue #7.
#
# Solution: a single OS process (the daemon) owns those operations. Every
# per-session heartbeat calls ensure_daemon_running() — the daemon either is
# already alive (no-op) or gets lazy-spawned detached. flock guarantees the
# singleton: if multiple sessions race to spawn, only one daemon acquires
# the exclusive lock; the rest exit cleanly. The fd holding the flock stays
# open for the daemon's entire lifetime; the kernel releases it on death.
#
# Everything here is read/write through state.atomic_write so a daemon
# crashing mid-write leaves no half-written sentinel.

from __future__ import annotations

import errno
import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import state

# Heartbeat staleness window. The daemon writes daemon.heartbeat.ts on every
# loop tick (≤ 60 s) AND periodically while a workload subprocess is running;
# if a session sees the ts older than this, it treats the daemon as stuck even
# if its PID is still alive. 1800 s (30 min) is wider than any documented
# workload (marketplace-refresh on 276 marketplaces ~10 min, user-plugins-update
# across ~80 plugins ~7 min) — false-stale alarms must be near-impossible.
DEFAULT_DAEMON_STALE_SECONDS = 1800


def global_state_dir() -> Path:
    """Return the system-wide janitor state directory.

    Resolution order:
      1. $JANITOR_GLOBAL_STATE_DIR if set (escape hatch for tests / weird hosts).
      2. $XDG_STATE_HOME/janitor/ when XDG_STATE_HOME is set (Linux default).
      3. ~/.claude/janitor-global-state/ everywhere else (the canonical home —
         it sits inside Claude Code's own state tree so the user already
         expects janitor data to live there, and it's not in any per-project
         tree so no per-worktree split).
    """
    override = os.environ.get("JANITOR_GLOBAL_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg).expanduser().resolve() / "janitor"
    return Path.home() / ".claude" / "janitor-global-state"


def init_global_state() -> Path:
    """Create the global state dir if missing. Idempotent. Return its path."""
    d = global_state_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------- file paths (private; callers use the named helpers below) -------

def _flock_path() -> Path: return global_state_dir() / "daemon.flock"
def _pid_path() -> Path: return global_state_dir() / "daemon.pid"
def _heartbeat_path() -> Path: return global_state_dir() / "daemon.heartbeat.ts"
def _killswitch_path() -> Path: return global_state_dir() / "kill-switch.flag"
def _spawn_marker_path() -> Path: return global_state_dir() / "daemon.spawn-attempt.ts"


def daemon_pid() -> Optional[int]:
    """Read daemon.pid → int, or None if missing / malformed."""
    p = _pid_path()
    if not p.is_file():
        return None
    try:
        raw = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw or not raw.isdigit():
        return None
    return int(raw)


def write_daemon_pid(pid: int) -> None:
    state.atomic_write(_pid_path(), str(int(pid)))


def remove_daemon_pid() -> None:
    try:
        _pid_path().unlink()
    except FileNotFoundError:
        pass
    except OSError:
        # Best-effort cleanup; the next daemon will overwrite anyway.
        pass


def write_heartbeat(now: Optional[int] = None) -> None:
    state.atomic_write(_heartbeat_path(), str(int(now if now is not None else time.time())))


def read_heartbeat() -> int:
    return state.read_int_state(_heartbeat_path(), 0)


def kill_switch_present() -> bool:
    return _killswitch_path().is_file()


# ---------- liveness ------------------------------------------------------

def _process_exists(pid: int) -> bool:
    """True iff pid is a running process owned by this uid (or we can signal it).

    `kill(pid, 0)` returns silently when the process exists and we have
    permission, raises ProcessLookupError (ESRCH) if not, and raises
    PermissionError (EPERM) if the process exists under a different uid (we
    treat that as alive — defensively, since a foreign-uid PID collision
    after a reboot is exceedingly rare on a single-user machine).
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        return exc.errno != errno.ESRCH


def daemon_is_alive(max_silence_s: int = DEFAULT_DAEMON_STALE_SECONDS) -> bool:
    """True iff the daemon's PID is alive AND its heartbeat is recent.

    Liveness requires BOTH:
      * daemon.pid resolves to a live process (defends against pid file
        survival across daemon crash + immediate restart cycle), and
      * daemon.heartbeat.ts was updated within `max_silence_s` (defends
        against a hung daemon whose process is technically alive but no
        longer making progress — issue #7's compounding failure mode).

    Returns False also when either sentinel is missing. The caller can then
    safely attempt a spawn (which is itself race-safe via flock).
    """
    pid = daemon_pid()
    if pid is None or not _process_exists(pid):
        return False
    hb = read_heartbeat()
    if hb <= 0:
        return False
    return (int(time.time()) - hb) <= max_silence_s


# ---------- singleton flock ----------------------------------------------

def acquire_singleton_flock() -> Optional[int]:
    """Acquire the exclusive non-blocking flock on daemon.flock.

    Return the fd on success — caller MUST keep it open for the daemon's
    lifetime. Returns None when another instance already holds the lock
    (the only safe semantic for a singleton: don't block, just abort).

    The flock is the source of truth for "is a daemon alive RIGHT NOW".
    The PID file and heartbeat are diagnostic conveniences; the flock is
    what actually prevents two daemons from running.
    """
    init_global_state()
    path = _flock_path()
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (BlockingIOError, OSError) as exc:
        # EAGAIN / EWOULDBLOCK → already held; anything else → unexpected.
        try:
            os.close(fd)
        finally:
            pass
        if isinstance(exc, BlockingIOError) or getattr(exc, "errno", None) in (errno.EAGAIN, errno.EWOULDBLOCK):
            return None
        # Unexpected — surface to logs but don't crash the caller.
        state.log_line("daemon", f"unexpected flock error: {exc}")
        return None


def release_singleton_flock(fd: int) -> None:
    """Close the fd; the kernel releases the flock as a side effect.

    Best-effort: a daemon shutting down would prefer a clean release, but
    the kernel will release on process death regardless, so closing twice
    or closing a stale fd is harmless.
    """
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


# ---------- spawn ---------------------------------------------------------

def daemon_script_path() -> Path:
    """Resolve scripts/daemon.py absolute path.

    The detectors and dispatch live under scripts/; this module is under
    scripts/lib/. Walking one parent up from __file__'s dir gets us scripts/.
    """
    return Path(__file__).resolve().parent.parent / "daemon.py"


def spawn_daemon_detached() -> Optional[int]:
    """Spawn the daemon as a fully-detached child. Return child PID or None.

    Detached means:
      * stdin/stdout/stderr → /dev/null (no FDs the parent must keep alive),
      * start_new_session=True → its own process group (immune to the
        parent's SIGHUP / terminal close),
      * no `wait()` from the caller (Popen object discarded).

    Race-safe: if multiple sessions call this at once, every spawned child
    races for the singleton flock; only one wins and continues the loop,
    the rest exit immediately on flock failure.
    """
    init_global_state()
    state.atomic_write(_spawn_marker_path(), str(int(time.time())))
    script = daemon_script_path()
    if not script.is_file():
        state.log_line("daemon", f"daemon script missing at {script} — cannot spawn")
        return None
    try:
        # Use sys.executable + script path explicitly so we don't depend on
        # an `uv` shebang being honored under every parent (cron, subshells,
        # etc.). The daemon script itself is PEP 723 — but invoking it via
        # `uv run --script` directly works on every host that has uv.
        # We prefer `uv run` because it brings the PEP 723 deps; if uv is
        # missing we fall back to plain python (and the daemon will detect
        # any import errors and exit gracefully).
        cmd_uv = ["uv", "run", "--script", "--quiet", str(script)]
        proc = subprocess.Popen(  # noqa: S603 - explicit args, no shell
            cmd_uv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        return proc.pid
    except FileNotFoundError:
        # uv missing → try plain python (the daemon's PEP 723 deps will be
        # missing, but the daemon detects and logs that itself).
        try:
            proc = subprocess.Popen(  # noqa: S603
                [sys.executable, str(script)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
            return proc.pid
        except OSError as exc:
            state.log_line("daemon", f"fallback spawn failed: {exc}")
            return None
    except OSError as exc:
        state.log_line("daemon", f"spawn failed: {exc}")
        return None


def ensure_daemon_running(max_silence_s: int = DEFAULT_DAEMON_STALE_SECONDS) -> bool:
    """If the daemon is dead AND not kill-switched AND enabled, spawn it.

    Cheap (file stat + one syscall) when the daemon is already alive — safe
    to call at the top of every heartbeat fire. Returns the post-call best-
    estimate of liveness:
      * True when the daemon was already alive.
      * True when we spawned successfully (the child may still be racing the
        flock, but a spawn was issued).
      * False when the kill switch is set, the master `daemon_enabled` knob
        is off, or the spawn could not happen.

    The master switch is `CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED` (truthy by
    default). When false, the daemon is never lazy-spawned AND every
    per-session shim becomes a silent no-op (the shims call us first; we
    return False, they exit).
    """
    if kill_switch_present():
        return False
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED", True):
        return False
    if daemon_is_alive(max_silence_s=max_silence_s):
        return True
    spawn_daemon_detached()
    return True
