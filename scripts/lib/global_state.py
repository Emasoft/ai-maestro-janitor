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

import contextlib
import errno
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator, Optional

import state

# Heartbeat staleness window. The daemon writes daemon.heartbeat.ts on every
# loop tick (≤ 60 s) AND every 10 s while a workload subprocess is running
# (_WORKLOAD_HEARTBEAT_TICK_SEC in daemon.py); if a session sees the ts older
# than this, it treats the daemon as stuck even if its PID is still alive.
# 1800 s (30 min) is the heartbeat-SILENCE bound, NOT a task-duration bound:
# a single bulk refresh can legitimately run for many minutes (a real one was
# measured at 1641 s / 27 min) yet ticks the heartbeat every 10 s the whole
# time, so a healthy-but-slow workload never looks silent for 1800 s — which
# is exactly why liveness keys on this heartbeat, not on per-task completion
# stamps (those age past one cadence during a long run and would false-alarm).
DEFAULT_DAEMON_STALE_SECONDS = 1800

# Minimum interval between two lazy-spawn attempts (seconds). ensure_daemon_running()
# stamps daemon.spawn-attempt.ts on every spawn and refuses to re-spawn within this
# window. Without it, a daemon that dies immediately on every start (broken PEP-723
# dep resolution, import error, read-only global_state_dir) would be re-spawned by
# EVERY heartbeat fire of EVERY session — unbounded churn (and on an NFS/network mount
# where flock is unreliable, briefly-coexisting daemons). The marker damps that to one
# attempt per window. Sized at ~2x the expected daemon startup cost so a healthy
# spawn-die-retry still recovers within a heartbeat or two, but a hard-broken daemon
# stops thrashing. Overridable for tests / slow hosts via the env var below.
_DEFAULT_MIN_SPAWN_INTERVAL_SECONDS = 90

# Crash-loop circuit-breaker (TRDD-7100178d Phase 4, Pillar 0). The per-attempt
# throttle above damps churn but a daemon that dies on EVERY start would still be
# re-spawned once per window forever. When _CRASH_LOOP_SPAWN_LIMIT attempts land
# inside _CRASH_LOOP_WINDOW_S, ensure_daemon_running refuses further spawns until
# attempts age out of the window (no extra cool-off state needed — the refusal
# itself stops new history entries, so the window naturally drains). With the
# 90 s throttle, a die-on-start daemon trips this after ~7.5 min, then retries
# roughly twice an hour instead of 40 times.
_CRASH_LOOP_SPAWN_LIMIT = 5
_CRASH_LOOP_WINDOW_S = 1800
_SPAWN_HISTORY_KEEP = 20  # ring length of daemon.spawn-history (one epoch per line)

# Wedged-daemon kill escalation (Pillar 0). After SIGTERM, wait this long for the
# process to exit before SIGKILL — a SIGSTOP'd (wedged) process never DELIVERS the
# queued SIGTERM, so the escalation is mandatory, not a nicety. SIGKILL always works
# on stopped processes.
_WEDGE_TERM_GRACE_S = 2.0
_WEDGE_KILL_GRACE_S = 1.0


# TRDD-2U8AH82F: the daemon state's CANONICAL home is the plugin DATA dir (backed up,
# preserved across plugin updates, purged only on uninstall). The old
# ~/.claude/janitor-global-state/ was an UNOFFICIAL folder — not backed up, orphaned by
# plugin purge. The move is a STAGED HANDOVER, not a flip: while an existing install has
# not migrated yet, everything keeps resolving the LEGACY dir; the daemon (the single
# writer, under its flock) performs the one-time copy and stamps this marker in the NEW
# dir — only then does resolution flip machine-wide.
_MIGRATION_MARKER = "migrated-from-legacy.ts"


def _legacy_global_state_dir() -> Path:
    return Path.home() / ".claude" / "janitor-global-state"


def _data_global_state_dir() -> Path:
    return (
        Path.home() / ".claude" / "plugins" / "data"
        / "ai-maestro-janitor-ai-maestro-plugins" / "global-state"
    )


def global_state_dir() -> Path:
    """Return the system-wide janitor state directory.

    Resolution order (TRDD-2U8AH82F):
      1. $JANITOR_GLOBAL_STATE_DIR if set (escape hatch for tests / weird hosts —
         ABSOLUTE priority, the whole test suite relies on it).
      2. $XDG_STATE_HOME/janitor/ when XDG_STATE_HOME is set (Linux default —
         already an official location, not part of the migration).
      3. The plugin DATA dir `.../plugins/data/<janitor>/global-state/` once the
         daemon has stamped the migration marker there, OR on a FRESH install
         (no legacy dir to migrate).
      4. The legacy ~/.claude/janitor-global-state/ while a not-yet-migrated
         install still has one — reads AND writes stay consistent with a
         possibly-older daemon until the single-writer migration flips the marker.
    """
    override = os.environ.get("JANITOR_GLOBAL_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg).expanduser().resolve() / "janitor"
    new = _data_global_state_dir()
    legacy = _legacy_global_state_dir()
    if (new / _MIGRATION_MARKER).is_file() or not legacy.is_dir():
        return new
    return legacy


def _legacy_read_path(name: str) -> Optional[Path]:
    """Dual-read window (TRDD-2U8AH82F): after the migration flips resolution to the
    DATA dir, a not-yet-updated session's OLD code may still write control flags at
    the LEGACY path. Flag READERS therefore also probe legacy while it exists — a
    fleet stop must never be missed because of version skew. Never active under the
    env override (test isolation), and gone entirely once the legacy dir is retired
    (fallback removal is the EHT follow-up, 2 releases out)."""
    if os.environ.get("JANITOR_GLOBAL_STATE_DIR"):
        return None
    legacy = _legacy_global_state_dir()
    if legacy.is_dir() and global_state_dir() != legacy:
        return legacy / name
    return None


def init_global_state() -> Path:
    """Create the global state dir if missing. Idempotent. Return its path."""
    d = global_state_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


# Files that must NOT be copied by the migration: the kernel locks are dir-bound
# (copying a flock file copies nothing kernel-side, and a stray copy invites a
# split-brain read), and the pid is re-published by the migrating daemon itself.
_MIGRATION_SKIP = frozenset({
    "daemon.flock", "daemon.pid", "marketplace-op.lock", "oauth-rotator-tick.lock",
})


def migrate_global_state_to_data_dir() -> Optional[int]:
    """One-time staged migration legacy → plugin DATA dir (TRDD-2U8AH82F).

    MUST be called ONLY by the daemon, immediately after it acquired the singleton
    flock — pre-migration that flock lives at the LEGACY path, so the caller is
    provably the machine's single writer. Sequence (the FLOCK-MOVES-LAST invariant):

      1. copy every state file/dir (minus kernel locks + pid) legacy → NEW;
      2. acquire the NEW dir's daemon.flock BEFORE stamping the marker — from that
         instant the caller holds BOTH flocks, so no window exists where a second
         daemon could take the NEW lock while we still guard only the legacy one;
      3. stamp the migration marker (the atomic switch every `global_state_dir()`
         call resolves on) and drop a tombstone README in the legacy dir.

    The legacy dir is NEVER deleted here — old-code sessions keep reading it, the
    dual-read window covers their flag writes, and retirement is the EHT follow-up
    two releases out. Returns the NEW flock fd (caller must keep it open for the
    daemon's lifetime) when a migration happened; None when there was nothing to
    do (env override, XDG host, fresh install, already migrated) or on any
    failure (fail-open: staying on legacy is always safe)."""
    if os.environ.get("JANITOR_GLOBAL_STATE_DIR") or os.environ.get("XDG_STATE_HOME"):
        return None
    legacy = _legacy_global_state_dir()
    if global_state_dir() != legacy:
        return None  # fresh install or already migrated — nothing to hand over
    new = _data_global_state_dir()
    try:
        new.mkdir(parents=True, exist_ok=True)
        for src in legacy.iterdir():
            if src.name in _MIGRATION_SKIP or src.name.endswith(".tmp"):
                continue
            dst = new / src.name
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif not dst.exists():  # idempotent: a prior partial copy wins
                shutil.copy2(src, dst)
    except OSError:
        return None
    # FLOCK MOVES LAST: take the NEW lock while still holding the legacy one.
    fd = None
    try:
        fd = os.open(new / "daemon.flock", os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        return None  # someone else holds the NEW lock — do NOT flip the marker
    try:
        marker = new / _MIGRATION_MARKER
        tmp = marker.with_name(marker.name + f".tmp.{os.getpid()}")
        tmp.write_text(f"{int(time.time())}\n", encoding="utf-8")
        os.replace(tmp, marker)
    except OSError:
        with contextlib.suppress(OSError):
            os.close(fd)
        return None
    with contextlib.suppress(OSError):
        (legacy / "README-MOVED.txt").write_text(
            "This janitor state dir was MIGRATED to the plugin DATA dir:\n"
            f"  {new}\n"
            "Kept only as a read-fallback for not-yet-updated sessions; safe to\n"
            "remove after every session runs a janitor >= the migration release.\n",
            encoding="utf-8",
        )
    return fd


# ---------- file paths (private; callers use the named helpers below) -------

def _flock_path() -> Path: return global_state_dir() / "daemon.flock"
def _pid_path() -> Path: return global_state_dir() / "daemon.pid"
def _heartbeat_path() -> Path: return global_state_dir() / "daemon.heartbeat.ts"
def _killswitch_path() -> Path: return global_state_dir() / "kill-switch.flag"
def _spawn_marker_path() -> Path: return global_state_dir() / "daemon.spawn-attempt.ts"
def _spawn_history_path() -> Path: return global_state_dir() / "daemon.spawn-history"
def _reload_flag_path() -> Path: return global_state_dir() / "reload-needed.flag"
def _skills_reload_flag_path() -> Path: return global_state_dir() / "skills-reload-needed.flag"
def _marketplace_lock_path() -> Path: return global_state_dir() / "marketplace-op.lock"
def _oauth_rotator_lock_path() -> Path: return global_state_dir() / "oauth-rotator-tick.lock"


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
    # Dual-read (TRDD-2U8AH82F): a fleet STOP set by an old-code session at the
    # legacy path must still be honored after the migration flipped resolution.
    if _killswitch_path().is_file():
        return True
    legacy = _legacy_read_path("kill-switch.flag")
    return legacy is not None and legacy.is_file()


def set_kill_switch(reason: str = "") -> None:
    """Create the kill-switch flag — the machine-wide STOP (TRDD-56d24c02 follow-up).
    The running daemon sees it on its next loop and exits, AND ``ensure_daemon_running``
    stops lazy-spawning it — so a deliberate stop is NOT resurrected by either path.
    ``/janitor-global-arm`` clears it to revive. Written atomically; content is advisory."""
    init_global_state()
    path = _killswitch_path()
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(reason or "stopped", encoding="utf-8")
    os.replace(tmp, path)


def clear_kill_switch() -> None:
    """Remove the kill-switch flag so the daemon can be lazy-spawned again — the revive
    half of the disarm/arm pair. Idempotent (a missing flag is fine)."""
    _killswitch_path().unlink(missing_ok=True)


def _maintenance_path() -> Path:
    return global_state_dir() / "maintenance-mode.flag"


def maintenance_mode_present() -> bool:
    """True iff the machine-wide MAINTENANCE flag is set (/janitor-global-maintenance,
    TRDD-FPL60EKV). Distinct from the kill-switch and global-pause: those STOP every
    session's heartbeat (self-disarm → the prompt cache dies → the next real turn pays a
    1.0x REWRITE), whereas maintenance KEEPS every session's heartbeat firing but does ONLY
    the cache refresh (no detectors, no daemon tasks). It is the fleet-wide "keep every
    project's cache warm at the 0.1x cache-READ rate instead of letting it die and paying
    the 1.0x rewrite" control — ~1/10 the cost. The daemon idles its task workloads while it
    is set (like a pause); `/janitor-global-maintenance` sets it, `-off` clears it."""
    if _maintenance_path().is_file():
        return True
    legacy = _legacy_read_path("maintenance-mode.flag")  # dual-read, TRDD-2U8AH82F
    return legacy is not None and legacy.is_file()


def set_maintenance_mode(reason: str = "") -> None:
    """Set the machine-wide MAINTENANCE flag — every session's heartbeat drops to
    cache-refresh-only fires (no chores) and the daemon idles its task workloads, until
    `clear_maintenance_mode`. Written atomically; content is advisory."""
    init_global_state()
    path = _maintenance_path()
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(reason or "maintenance", encoding="utf-8")
    os.replace(tmp, path)


def clear_maintenance_mode() -> None:
    """Clear the machine-wide MAINTENANCE flag so heartbeats resume FULL fires (chores) and
    the daemon resumes its task workloads. Idempotent (a missing flag is fine)."""
    _maintenance_path().unlink(missing_ok=True)


def _global_pause_path() -> Path:
    return global_state_dir() / "global-pause.flag"


def global_pause_present() -> bool:
    """True iff the machine-wide PAUSE flag is set (TRDD-a3fa4d5d). Distinct from the
    kill-switch: a PAUSE leaves the daemon ALIVE but idle (it skips all task workloads
    while this is present), and every session's heartbeat no-ops — a temporary,
    teardown-free silence. `/janitor-global-pause` sets it; `/janitor-global-unpause`
    clears it. Contrast the kill-switch, which makes the daemon EXIT (the true stop)."""
    if _global_pause_path().is_file():
        return True
    legacy = _legacy_read_path("global-pause.flag")  # dual-read, TRDD-2U8AH82F
    return legacy is not None and legacy.is_file()


def set_global_pause(reason: str = "") -> None:
    """Set the machine-wide PAUSE flag — the daemon idles (stays alive, keeps ticking
    its heartbeat so it is not seen as wedged) and per-session heartbeats no-op, until
    `clear_global_pause`. Written atomically; content is advisory."""
    init_global_state()
    path = _global_pause_path()
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(reason or "paused", encoding="utf-8")
    os.replace(tmp, path)


def clear_global_pause() -> None:
    """Clear the machine-wide PAUSE flag — the daemon resumes running due tasks on its
    next loop and sessions resume emitting drift. Idempotent (a missing flag is fine)."""
    _global_pause_path().unlink(missing_ok=True)


# ---------- version-update REQUEST (release-triggered self-update, TRDD-Y9KM5RCJ) ----
#
# A per-session `version-update` detector notices the plugin cache is behind the latest
# GitHub release ~5 min after a release lands, but must NOT run `claude plugin update`
# itself — the daemon is the single global writer (issue #7 / PRRD S2.1). So the detector
# RAISES this request flag and the daemon CONSUMES it on its next loop (≤ ~60 s), running
# task_version_update NOW instead of on its 6 h beat. A simple boolean flag consumed
# clear-before-run by the daemon: a run that fails is re-signalled by the detector's next
# ~5 min fire, never lost. NO legacy dual-read (unlike kill-switch/reload): this flag
# exists only in code at or past this release, so both writer (detector) and reader
# (daemon) are new — there is no version-skew writer at the legacy path to miss.

def _version_update_request_path() -> Path:
    return global_state_dir() / "version-update-requested.flag"


def version_update_requested_present() -> bool:
    """True iff a session detector has requested an immediate janitor self-update
    (TRDD-Y9KM5RCJ). The daemon checks this each loop and, when set, runs the
    version-update task NOW rather than waiting for the 6 h beat."""
    return _version_update_request_path().is_file()


def request_version_update(reason: str = "") -> None:
    """Raise the release-triggered self-update request. Idempotent (re-writing the same
    flag is harmless; the daemon clears it on consume). Written atomically; content is
    advisory. Best-effort — a write failure just falls back to the 6 h beat (fail-open),
    so this never crashes the read-only detector that calls it."""
    try:
        init_global_state()
        path = _version_update_request_path()
        tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
        tmp.write_text(reason or "requested", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def clear_version_update_request() -> None:
    """Clear the release-triggered self-update request. The daemon calls this BEFORE
    running the update (clear-before-run: a run that fails is re-signalled by the
    detector's next ~5 min fire, never lost to a clear-after-run crash). Idempotent."""
    _version_update_request_path().unlink(missing_ok=True)


# ---------- per-plugin update QUEUE (universal auto-update, TRDD-YMTUPQER) -----------
#
# Generalizes the version-update self flag above from "update the janitor" to "update ANY
# plugin at ANY scope". The per-session `plugin-updates` detector raises a request for a
# behind USER-scope plugin (it must NOT run `claude plugin update --scope user` itself — the
# daemon is the single global writer, issue #7 / PRRD S2.1); the daemon CONSUMES each request
# on its loop (≤ ~60 s) and runs the update. A JSON map keyed `<plugin_id>|<scope>` (same
# shape as fleet-injections.json), consumed clear-before-run: a run that fails is re-signalled
# by the detector's next ~5 min fire, never stranded. project/local scope keeps updating
# per-session in the detector (per-repo, not a machine-global race), so only user-scope goes
# through this queue. NO legacy dual-read — new-code-only writer (detector) + reader (daemon).

def _plugin_update_requests_path() -> Path:
    return global_state_dir() / "plugin-update-requests.json"


@contextlib.contextmanager
def _plugin_requests_lock() -> Iterator[None]:
    """Serialise the read-modify-write of plugin-update-requests.json across processes.

    N sessions' `plugin-updates` detectors AND the daemon's consume all mutate this one shared
    map, so a lock-free read-modify-write silently DROPS a request (lost update): two writers
    both read {}, each adds its own key, and the second write clobbers the first. Unlike the
    marketplace lock (skip-and-retry, because it wraps a ~10-min operation), this critical
    section is microseconds — read + rewrite a tiny JSON — so a BLOCKING exclusive flock is
    correct and deadlock-free. Fail-open: if the lock cannot be taken (no fcntl, fs error) the
    body still runs unlocked rather than crash the read-only detector that called it."""
    fd = None
    try:
        init_global_state()
        fd = os.open(str(global_state_dir() / "plugin-update-requests.lock"),
                     os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
            fd = None
    try:
        yield
    finally:
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass


def _read_plugin_update_requests_raw() -> dict:
    """The `{"<plugin_id>|<scope>": {plugin_id, scope, reason}}` map, or {} on a
    missing/corrupt file (fail-open)."""
    try:
        data = json.loads(_plugin_update_requests_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def request_plugin_update(plugin_id: str, scope: str, reason: str = "") -> None:
    """Enqueue a request for the daemon to update ``plugin_id`` at ``scope`` (TRDD-YMTUPQER).
    Keyed ``<plugin_id>|<scope>``; idempotent (re-enqueue overwrites the same key). Atomic;
    best-effort/fail-open — a write hiccup just falls back to the daemon's 1 h user-scope
    sweep, so this never crashes the read-only detector that calls it."""
    key = f"{plugin_id}|{scope}"
    with _plugin_requests_lock():
        data = _read_plugin_update_requests_raw()
        data[key] = {"plugin_id": plugin_id, "scope": scope, "reason": reason}
        try:
            path = _plugin_update_requests_path()
            tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass


def plugin_update_requests() -> list[dict]:
    """The queued per-plugin update requests (each ``{plugin_id, scope, reason}``). Fail-open
    ``[]`` on a missing/corrupt file. The daemon reads this each loop and consumes each entry
    clear-before-run."""
    return list(_read_plugin_update_requests_raw().values())


def clear_plugin_update_request(plugin_id: str, scope: str) -> None:
    """Remove one consumed request (``<plugin_id>|<scope>``). The daemon calls this BEFORE
    running the update (clear-before-run: a run that fails is re-signalled by the detector's
    next ~5 min fire). Idempotent, atomic, fail-open."""
    key = f"{plugin_id}|{scope}"
    with _plugin_requests_lock():
        data = _read_plugin_update_requests_raw()
        if key not in data:
            return
        del data[key]
        try:
            path = _plugin_update_requests_path()
            if not data:
                path.unlink(missing_ok=True)
                return
            tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass


# ---------- fleet-stop flag + injection stamps (TRDD-ME8V2YJF) ------------
#
# The daemon-driven fleet disarm/pause (fleet_stop.py) reaches every OTHER running
# janitor session and types the stop command into it. `fleet_stop_flag_state`
# collapses the two existing machine-wide flags into the single state that policy
# consumes; the injection-stamp map dedupes so a flag that stays set does not
# re-inject every daemon beat. The stamps are pure runtime state — losing them only
# risks a harmless re-inject (the target session ignores a redundant /janitor-disarm),
# so every writer here is fail-open (FS errors are swallowed, logic bugs are not).

def fleet_stop_flag_state() -> str | None:
    """The current machine-wide fleet-stop flag, or None when neither is set. ``disarm``
    (the kill-switch) DOMINATES ``pause``: a disarm is the true stop (delete the cron),
    so it takes precedence over the softer pause. The daemon's fleet-stop beat reads
    this to decide which slash command to inject into every other session."""
    if kill_switch_present():
        return "disarm"
    if global_pause_present():
        return "pause"
    return None


def _fleet_injections_path() -> Path:
    return global_state_dir() / "fleet-injections.json"


def _read_fleet_injections_raw() -> dict:
    """The `{dedupe_key: epoch}` map, or {} on a missing/corrupt file (fail-open)."""
    try:
        data = json.loads(_fleet_injections_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def record_fleet_injection(pid: int, flag_state: str, now: int) -> None:
    """Record that ``(pid, flag_state)`` was injected so a held flag does not re-inject
    every daemon beat. Keyed ``"{pid}:{flag_state}"`` → epoch ``now`` (passed in, never
    read from the clock here). Atomic write; fail-OPEN on FS error (a lost stamp only
    risks a redundant inject, which the target session no-ops)."""
    data = _read_fleet_injections_raw()
    data[f"{pid}:{flag_state}"] = int(now)
    try:
        init_global_state()
        path = _fleet_injections_path()
        tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def fleet_injections_seen() -> set[str]:
    """The set of ``"{pid}:{flag_state}"`` dedupe keys already injected (fail-open
    empty on a missing/corrupt file). The daemon passes this to
    ``fleet_stop.select_stop_targets`` so already-stopped sessions are skipped."""
    return set(_read_fleet_injections_raw().keys())


def clear_fleet_injections(flag_state: str | None = None) -> None:
    """Forget injection stamps so a re-set flag re-injects. ``flag_state=None`` clears
    ALL (called when no fleet-stop flag is set); a specific state clears only its
    stamps. Idempotent, atomic, fail-open."""
    if flag_state is None:
        _fleet_injections_path().unlink(missing_ok=True)
        return
    data = _read_fleet_injections_raw()
    remaining = {k: v for k, v in data.items() if not k.endswith(f":{flag_state}")}
    try:
        path = _fleet_injections_path()
        if not remaining:
            path.unlink(missing_ok=True)
            return
        tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
        tmp.write_text(json.dumps(remaining), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


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

def acquire_singleton_flock(*, blocking: bool = False) -> Optional[int]:
    """Acquire the exclusive flock on daemon.flock.

    Default (``blocking=False``): NON-blocking. Returns the fd on success — caller
    MUST keep it open for the daemon's lifetime — or None when another instance
    already holds the lock (the safe singleton semantic for a session-spawned
    daemon that loses the race: don't block, just abort).

    ``blocking=True``: WAIT for the lock instead of aborting. This is for the
    OS-keepalive (L0) daemon, which runs under launchd/systemd KeepAlive: if it
    aborted on a held lock it would IMMEDIATELY be respawned, busy-looping
    spawn→abort→respawn every ThrottleInterval whenever a session-spawned daemon
    holds the singleton. Instead it blocks (idle, zero churn) until the holder
    exits, then takes over (TRDD-71ABD7V7). Safe because while blocked it has not
    yet written its pid or installed signal handlers, so a launchd bootout SIGTERM
    kills it cleanly via the default disposition with nothing to unwind.

    The flock is the source of truth for "is a daemon alive RIGHT NOW". The PID
    file and heartbeat are diagnostic conveniences; the flock is what actually
    prevents two daemons from running.
    """
    init_global_state()
    path = _flock_path()
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    lock_op = fcntl.LOCK_EX if blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        while True:
            try:
                fcntl.flock(fd, lock_op)
                return fd
            except InterruptedError:
                # A signal interrupted a BLOCKING wait → retry. (Non-blocking never
                # blocks, so it never raises this; if it somehow does, fall through to
                # the unexpected-error path below.)
                if blocking:
                    continue
                raise
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


# ---------- marketplace-operation lock -----------------------------------
#
# A SEPARATE cross-process flock (distinct from the singleton daemon flock)
# that serialises every `claude plugin marketplace update` invocation. The
# singleton flock guarantees one DAEMON; it does NOT stop the daemon's bulk
# refresh and a per-session single-market update — different PROCESSES — from
# running `claude plugin marketplace update` simultaneously and corrupting
# ~/.claude/plugins/marketplaces/. Per-project PID dedup could not prevent
# that cross-session race (issue #7); only a shared OS-level lock can.
#
# Non-blocking BY DESIGN: a loser SKIPS its turn rather than waiting. Both the
# daemon (20-min cadence) and the per-session detectors (5-min cadence) re-fire
# on their own schedule, so skipping is safe; blocking would risk wedging a
# session's heartbeat turn behind the daemon's ~10-min bulk refresh, or
# tripping the daemon's own workload timeout. Skip-and-retry is deadlock-proof.

def acquire_marketplace_lock() -> Optional[int]:
    """Non-blocking exclusive flock on marketplace-op.lock.

    Return the fd on success — the caller MUST release it via
    release_marketplace_lock() once the marketplace operation finishes.
    Return None when another process already holds it; the caller MUST then
    SKIP the marketplace operation this round (never block on it).
    """
    init_global_state()
    fd = os.open(str(_marketplace_lock_path()), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (BlockingIOError, OSError) as exc:
        try:
            os.close(fd)
        finally:
            pass
        if isinstance(exc, BlockingIOError) or getattr(exc, "errno", None) in (errno.EAGAIN, errno.EWOULDBLOCK):
            return None
        # Unexpected — surface to logs but don't crash the caller.
        state.log_line("daemon", f"unexpected marketplace-lock flock error: {exc}")
        return None


def release_marketplace_lock(fd: int) -> None:
    """Release the marketplace-op flock and close the fd. Best-effort."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


@contextlib.contextmanager
def marketplace_lock() -> Iterator[bool]:
    """Serialise a `claude plugin marketplace update` against every other process.

    Yields True when the lock was acquired (run the marketplace update), or
    False when another process holds it (SKIP this round — the caller re-fires
    on its normal cadence). Releases the lock on exit iff it was held.

        with gs.marketplace_lock() as got:
            if not got:
                # log "deferred (marketplace op in progress)"; return
                ...
            # safe to run `claude plugin marketplace update ...`
    """
    fd = acquire_marketplace_lock()
    try:
        yield fd is not None
    finally:
        if fd is not None:
            release_marketplace_lock(fd)


# ---------- oauth-rotator-tick lock --------------------------------------
#
# A SEPARATE cross-process flock (distinct from the singleton daemon flock AND
# the marketplace lock) that serialises every OAuth-rotator TICK against every
# other tick-class mutation. The daemon's 60 s `oauth-rotator-tick` and a human's
# manual `rotator.py tick`/`switch`/`migrate-slots` are different PROCESSES that
# both write state.json + the live/slot keychain; without a shared lock they race
# on a lost `last_switch_at`/`live_429_streak` update or two near-simultaneous
# switches that split the live credential from `state.live_email` (audit §3.4).
# Per-project PID dedup cannot prevent that cross-session race — only a shared
# OS-level lock can. The rotator is a machine-wide single-writer, exactly like the
# marketplace ops.
#
# Non-blocking BY DESIGN: a loser SKIPS its tick rather than waiting. The daemon
# re-fires every 60 s and a manual tick is a one-shot the user re-runs, so skipping
# is always safe; blocking would risk wedging a session's heartbeat turn or
# tripping the daemon's workload timeout. Skip-and-retry is deadlock-proof.

def acquire_oauth_rotator_lock() -> Optional[int]:
    """Non-blocking exclusive flock on oauth-rotator-tick.lock.

    Return the fd on success — the caller MUST release it via
    release_oauth_rotator_lock() once the rotator tick finishes. Return None when
    another process already holds it; the caller MUST then SKIP the tick this round
    (never block on it).
    """
    init_global_state()
    fd = os.open(str(_oauth_rotator_lock_path()), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (BlockingIOError, OSError) as exc:
        try:
            os.close(fd)
        finally:
            pass
        if isinstance(exc, BlockingIOError) or getattr(exc, "errno", None) in (errno.EAGAIN, errno.EWOULDBLOCK):
            return None
        # Unexpected — surface to logs but don't crash the caller.
        state.log_line("daemon", f"unexpected oauth-rotator-lock flock error: {exc}")
        return None


def release_oauth_rotator_lock(fd: int) -> None:
    """Release the oauth-rotator-tick flock and close the fd. Best-effort."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


@contextlib.contextmanager
def oauth_rotator_lock() -> Iterator[bool]:
    """Serialise an OAuth-rotator tick against every other tick-class process.

    Yields True when the lock was acquired (run the tick), or False when another
    process holds it (SKIP this round — the caller re-fires on its normal cadence).
    Releases the lock on exit iff it was held.

        with gs.oauth_rotator_lock() as got:
            if not got:
                # log "deferred (another rotator tick in progress)"; return
                ...
            # safe to run the rotator tick
    """
    fd = acquire_oauth_rotator_lock()
    try:
        yield fd is not None
    finally:
        if fd is not None:
            release_oauth_rotator_lock(fd)


@contextlib.contextmanager
def oauth_rotator_lock_wait(timeout_s: float = 60.0, poll_s: float = 0.25) -> Iterator[bool]:
    """Bounded-WAIT variant of `oauth_rotator_lock`, for a one-shot the caller must not drop.

    Skip-and-retry (the default above) is right for the TICK class: the daemon re-fires in
    60 s and a heartbeat turn must never block. It is wrong for an account CAPTURE. By the
    time a capture persists anything, a human has already completed an interactive browser
    OAuth flow, and the resulting token exists only in this process's memory — "skip, we'll
    get it next time" silently throws that work away. So wait for the (short) tick to
    finish instead.

    Still deadlock-proof: the wait is BOUNDED, so a wedged holder costs `timeout_s` and a
    clear failure, never a hang. Yields False on timeout — and the caller must then write
    NOTHING, so a lost race can never leave a half-filed account (a token in the keychain
    with no entry in state.json is an ORPHAN the rotator would never use).

    Not reentrant: never call this from a context that already holds the rotator lock (e.g.
    inside `rotator.main()`'s locked commands) — flock conflicts across open descriptions
    even within one process, so it would wait out the full timeout and fail."""
    deadline = time.time() + max(0.0, timeout_s)
    fd = acquire_oauth_rotator_lock()
    while fd is None and time.time() < deadline:
        time.sleep(poll_s)
        fd = acquire_oauth_rotator_lock()
    try:
        yield fd is not None
    finally:
        if fd is not None:
            release_oauth_rotator_lock(fd)


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
    _record_spawn_attempt()  # crash-loop bookkeeping (Pillar 0) — every spawn path counts
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


# ---------- reload GENERATION (Claude /reload-plugins after plugin auto-update) --
#
# The daemon STAMPS this marker with the current epoch when `claude plugin
# update` actually changed a plugin's version on disk. It is a MONOTONIC
# GENERATION, never cleared by a reading session. Each session's heartbeat
# compares it to a per-PROJECT `reload-acked.ts` (in dispatch._phase_plugin_reload)
# and emits a bare `[janitor-reload]` exactly once when the generation advances
# past what that project has acked.
#
# WHY a generation and not a single boolean flag: the old design wrote one global
# boolean and the FIRST session's dispatch phase CLEARED it right after emitting —
# so whichever session fired first consumed the one-shot nudge, and every OTHER
# live session (notably an autonomous fleet agent in a DIFFERENT project) never saw
# `[janitor-reload]` and kept running stale plugin code until restart. That is the
# exact failure a MANAGER-fleet session hit ("CPV agents not registered" while the
# on-disk plugin was fine). Stamping a never-cleared generation lets every
# project's heartbeat independently reload once per update. The flag FILE path is
# unchanged, so a still-running OLD-code session is surfaced once via its legacy
# is-present check during the one transition update that ships this code.

def _generation_from_file(p: Path) -> int:
    """Parse one generation-flag file: `<epoch>\\t<reason>` on the first line.
    Shared by the reload + skills-reload readers (and their legacy dual-reads)."""
    if not p.is_file():
        return 0
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return 0
    # Take the token before the tab, NOT the whole line (never all-digits).
    first_line = raw.splitlines()[0] if raw else ""
    gen_tok = first_line.partition("\t")[0].strip()
    if gen_tok.isdigit():
        return int(gen_tok)
    # Pre-generation content (a boolean "1" or a bare reason string) → treat as
    # "an update happened at an unknown time" so a never-acked session still
    # reloads once (1 is the smallest positive gen; any real epoch dwarfs it).
    return 1 if raw.strip() else 0


def reload_generation() -> int:
    """Return the reload generation (epoch the daemon last stamped after a
    plugin changed on disk), or 0 if none. NEVER mutated by a reader.
    Dual-reads the legacy dir during the migration window (TRDD-2U8AH82F) —
    max() wins, so a stamp from either era still triggers exactly one reload."""
    gen = _generation_from_file(_reload_flag_path())
    legacy = _legacy_read_path("reload-needed.flag")
    if legacy is not None:
        gen = max(gen, _generation_from_file(legacy))
    return gen


def reload_flag_present() -> bool:
    return reload_generation() > 0


def set_reload_flag(reason: str = "") -> None:
    """Stamp the reload generation (current epoch) after a plugin changed on
    disk. Format `<epoch>\\t<reason>`; the epoch is the generation each session
    compares against its per-project ack. Monotonic (wall-clock only advances)
    and NEVER cleared by a reader — clearing is precisely what starved concurrent
    sessions in the old single-flag design."""
    state.atomic_write(_reload_flag_path(), f"{int(time.time())}\t{reason}")


def clear_reload_flag() -> None:
    """Reset the reload generation. Used only by the disarm / manual-reset path;
    the normal heartbeat flow NEVER clears it (see set_reload_flag's WHY)."""
    try:
        _reload_flag_path().unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


# ---------- STANDALONE-skills reload generation (TRDD-LQU7OXXV follow-up) -----
#
# The plugin-reload generation above tracks `/reload-plugins` (skills/commands
# bundled INSIDE a plugin). This PARALLEL generation tracks `/reload-skills` —
# the command that reloads STANDALONE (non-plugin) skills/commands installed at
# local/project/user scope. `/janitor-global-reload-skills` stamps it; each
# session's heartbeat (dispatch `_phase_skills_reload`) compares it to a
# per-project `skills-reload-acked.ts` and emits `[janitor-reload-skills]` exactly
# once per bump — the same never-cleared-generation + per-project-ack design that
# stops one session starving another (see set_reload_flag's WHY). Kept a SEPARATE
# flag file so a plugin auto-update (which stamps ONLY the plugin generation) never
# forces a redundant standalone-skills reload, and vice-versa.

def skills_reload_generation() -> int:
    """Return the standalone-skills reload generation (epoch of the last
    `/janitor-global-reload-skills`), or 0 if none. NEVER mutated by a reader.
    Dual-reads the legacy dir during the migration window (TRDD-2U8AH82F) — an
    old-code session's global_control_cli may still stamp the legacy path."""
    gen = _generation_from_file(_skills_reload_flag_path())
    legacy = _legacy_read_path("skills-reload-needed.flag")
    if legacy is not None:
        gen = max(gen, _generation_from_file(legacy))
    return gen


def skills_reload_flag_present() -> bool:
    return skills_reload_generation() > 0


def set_skills_reload_flag(reason: str = "") -> None:
    """Stamp the standalone-skills reload generation (current epoch). Format
    `<epoch>\\t<reason>`; each session compares the epoch against its per-project
    ack. Monotonic (wall-clock only advances) and NEVER cleared by a reader —
    clearing would starve concurrent sessions (see set_reload_flag's WHY)."""
    state.atomic_write(_skills_reload_flag_path(), f"{int(time.time())}\t{reason}")


def clear_skills_reload_flag() -> None:
    """Reset the standalone-skills reload generation. Used only by a manual-reset
    path; the normal heartbeat flow NEVER clears it."""
    try:
        _skills_reload_flag_path().unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


# ---------- daemon-script staleness (self-restart on plugin upgrade) ---------

def _read_process_cmdline(pid: int) -> str:
    """Best-effort read of a running process's full command line.

    Uses `ps -p PID -o args=` which is POSIX-portable (works identically on
    macOS and every Linux). Returns "" on any failure — callers treat empty
    as "can't tell" and skip the staleness check rather than guess.
    """
    if pid <= 0:
        return ""
    try:
        proc = subprocess.run(  # noqa: S603 - explicit args, no shell
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


# The plugin cache lays a daemon out at
# `.../ai-maestro-plugins/ai-maestro-janitor/<semver>/scripts/daemon.py`, so the
# version segment is the `<semver>` that immediately follows the plugin-name path
# component. Anchoring on the leading slash + the plugin name avoids matching the
# `ai-maestro-plugins` marketplace dir that precedes it.
_CACHE_VERSION_RE = re.compile(r"/ai-maestro-janitor/(\d+\.\d+\.\d+)/")


def _cache_version_from_path(text: str) -> Optional[str]:
    """Extract the plugin cache `<version>` segment from a daemon script path.

    Returns the `<semver>` string embedded in `.../ai-maestro-janitor/<semver>/`,
    or None when `text` has no such segment (e.g. a non-cache install, the repo
    checkout, or the L0 keepalive entry from the FIXED DATA dir) — i.e. "not
    version-comparable by cache layout".
    """
    m = _CACHE_VERSION_RE.search(text)
    return m.group(1) if m else None


def _restart_decision(cmdline: str, expected: str, quarantined: set[str]) -> bool:
    """PURE core of daemon_needs_restart's version-RECENCY gate (B-2 / CC 2.1.200).

    Given the running daemon's argv `cmdline`, the `expected` current-cache
    `daemon.py` path (from the version driving THIS heartbeat), and the set of
    `quarantined` version strings, decide whether to SIGTERM-and-respawn. Split
    out as a pure function so the directionality logic is unit-testable without a
    live process. The WHY of each branch:

      * exact path match          → False: the daemon already runs the current
                                    cache's daemon.py; nothing to roll.
      * current cache is NEWER     → True:  normal roll-forward — a plugin update
                                    landed while the old daemon still ran old code.
      * current cache is OLDER     → restart ONLY iff the running (newer) daemon's
                                    version is QUARANTINED. This is the one CC
                                    2.1.200 fix: a mere path DIFFERENCE must not let
                                    an OLDER reinstalled/downgraded cache SIGTERM a
                                    NEWER running daemon and respawn itself from the
                                    older cache ("older build seizes the daemon").
                                    The single legitimate downgrade is C3
                                    auto-rollback DOWN to a known-good older version
                                    after the newer one was proven bad (quarantined).
      * same version, other path   → False: same code, don't thrash the daemon.
      * either version unparseable → True:  fail-safe to the pre-B-2 "roll on any
                                    diff" so a genuinely-relocated/reinstalled path
                                    still rolls. A non-cache path is almost always a
                                    real reinstall, not a downgrade, so restarting is
                                    the safe default when recency can't be proven.
    """
    if expected in cmdline:
        return False
    import version_update_lib as _vul  # lazy: keeps global_state's top-level import
                                       # graph thin for the many hooks/detectors that
                                       # import it but never call daemon_needs_restart.
    running_ver = _cache_version_from_path(cmdline)
    current_ver = _cache_version_from_path(expected)
    if running_ver is None or current_ver is None:
        return True  # can't locate a cache version in one path → fail-safe restart
    running_t = _vul.parse_semver(running_ver)
    current_t = _vul.parse_semver(current_ver)
    if running_t == (-1,) or current_t == (-1,):
        return True  # non-semver segment → fail-safe restart (same as above)
    if current_t > running_t:
        return True  # roll-forward — this heartbeat's cache is newer than the daemon
    if current_t < running_t:
        # Older heartbeat vs a newer running daemon: never downgrade UNLESS the newer
        # running version is quarantined (proven-bad → legitimate C3 rollback DOWN).
        return running_ver in quarantined
    return False  # same version, path differs only in location → no code change


def daemon_needs_restart() -> bool:
    """True iff the running daemon should be restarted from the current cache.

    Detects the autonomy gap that survives plugin updates without it: when
    the janitor plugin itself is auto-updated to a new cache version, the
    OLD daemon process is still running its OLD daemon.py from the old
    cache. Hooks/skills reload via `/reload-plugins` but the daemon's
    Python interpreter still holds the old code — bugs fixed in the new
    version remain unfixed in the running daemon.

    Comparison rule (RECENCY-gated — CC 2.1.200 parity / audit B-2): the
    running process's argv carries a path to
    `.../<plugin-cache-version>/scripts/daemon.py`. Our `daemon_script_path()`
    (called from dispatch — same `scripts/` dir as the version driving the
    heartbeat) gives the EXPECTED path. A restart is requested only when the
    current heartbeat's cache is NEWER than the running daemon's (roll-forward),
    or when the running daemon's version is now QUARANTINED (roll DOWN to a
    known-good older version). A mere path DIFFERENCE is NOT enough — an OLDER
    reinstalled cache must not SIGTERM a NEWER running daemon and reseat itself
    from the older cache. See `_restart_decision` for the full truth table.

    Returns False when the daemon isn't running, when we can't read its
    argv (foreign uid, race, ps unavailable), or when the recency gate says
    stay. A False return is always safe — the daemon will be restarted next
    time it actually crashes or stalls.
    """
    pid = daemon_pid()
    if pid is None or not _process_exists(pid):
        return False
    cmdline = _read_process_cmdline(pid)
    if not cmdline:
        return False
    # The OS-keepalive (L0) daemon runs the STABLE entry `daemon_keepalive_entry.py` from
    # the FIXED DATA path (TRDD-71ABD7V7); its argv is that entry, never a cache
    # `daemon.py`. The cache-path comparison below would therefore ALWAYS judge it "stale"
    # and SIGTERM it — and launchd would immediately respawn it, so the next heartbeat
    # SIGTERMs it again: an endless restart loop. It is NOT stale by that measure: launchd
    # owns its lifecycle and it re-stages its own DATA copy toward the freshest cache on
    # respawn (launchd_keepalive.restage / staged_is_current). Session-side restart must
    # leave it alone.
    if "daemon_keepalive_entry.py" in cmdline:
        return False
    expected = str(daemon_script_path().resolve())
    try:
        import version_update_lib as _vul
        quarantined = _vul.read_quarantine()
    except Exception:  # noqa: BLE001 — a recency-gate fault must never crash the heartbeat.
        # version_update_lib unavailable / quarantine read faulted → fall back to the
        # pre-B-2 contract (restart on any path diff) so a genuinely-changed path still
        # rolls. WHY safe: this only re-opens the older-vs-newer edge the gate would
        # otherwise block; a stale daemon that never rolls is the worse failure.
        return expected not in cmdline
    return _restart_decision(cmdline, expected, quarantined)


def request_daemon_restart() -> bool:
    """Send SIGTERM to a stale daemon so the next heartbeat lazy-spawns a new one.

    Returns True iff a SIGTERM was successfully delivered. The daemon's
    graceful-shutdown handler will release the singleton flock; the very
    next `ensure_daemon_running()` call (from this dispatch fire or the
    next one) will spawn a fresh daemon from the current cache version.

    Never raises — a failed signal is logged and ignored; the next fire
    will try again.
    """
    pid = daemon_pid()
    if pid is None or not _process_exists(pid):
        return False

    # IDENTITY RE-CHECK BEFORE THE KILL — `daemon.pid` is a FILE, and a pid is a reusable
    # integer. If the daemon died without clearing that file (SIGKILL, OOM, power loss) the
    # OS is free to hand its number to any new process, and `_process_exists(pid)` — a bare
    # `kill(pid, 0)` — cannot tell the difference: it answers "something is alive", never
    # "the daemon is alive". SIGTERMing on that answer means we can kill an innocent,
    # unrelated process that merely inherited the number — the user's editor, a build, a
    # database. Claude Code shipped this exact bug and fixed it in 2.1.200; we are not going
    # to re-ship it.
    #
    # `_read_process_cmdline` is what makes the check real: the pid must still be running a
    # janitor daemon. It returns "" when it cannot tell (ps missing/blocked), and an
    # unverifiable pid is NOT a licence to signal it — we refuse and let the next heartbeat
    # retry, because the cost of not restarting a stale daemon (it lingers one more tick) is
    # trivially smaller than the cost of killing the wrong process.
    cmdline = _read_process_cmdline(pid)
    if not cmdline:
        state.log_line(
            "daemon",
            f"daemon-restart: refusing to signal pid={pid} — cannot read its cmdline to "
            "confirm it is our daemon (a recycled pid could be any process)",
        )
        return False
    if "daemon.py" not in cmdline and "daemon_keepalive_entry.py" not in cmdline:
        # The pid is alive but is NOT the daemon → the pid was reused. Clear the stale pid
        # file so the next `ensure_daemon_running()` lazy-spawns a fresh daemon instead of
        # forever pointing at a stranger.
        state.log_line(
            "daemon",
            f"daemon-restart: pid={pid} is NOT a janitor daemon (recycled pid; cmdline="
            f"{cmdline[:120]!r}) — NOT signalling it; clearing the stale daemon.pid",
        )
        remove_daemon_pid()
        return False

    import signal as _signal
    try:
        os.kill(pid, _signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError) as exc:
        state.log_line("daemon", f"daemon-restart SIGTERM failed for pid={pid}: {exc}")
        return False
    state.log_line("daemon", f"daemon-restart: SIGTERM sent to pid={pid} (stale cache version)")
    return True


# ---------- Pillar 0 — self-resurrection (TRDD-7100178d Phase 4) -------------

def _process_alive_not_zombie(pid: int) -> bool:
    """True iff pid is alive AND not a zombie. The wedge-kill verdict needs this
    instead of bare _process_exists: kill(pid, 0) SUCCEEDS on a zombie, but a
    zombie has already RELEASED its flock (locks release at process death, not at
    reaping) — so for "does it still hold the singleton flock / need killing" a
    zombie counts as GONE. `ps -o stat=` is BSD+procps portable; a 'Z' state
    letter marks the zombie."""
    if not _process_exists(pid):
        return False
    try:
        proc = subprocess.run(  # noqa: S603 - explicit args, no shell
            ["ps", "-p", str(pid), "-o", "stat="],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return True  # can't tell → assume alive (the conservative direction here)
    if proc.returncode != 0:
        return False  # ps can't see it → gone
    return not (proc.stdout or "").strip().upper().startswith("Z")


def _record_spawn_attempt(now: Optional[int] = None) -> None:
    """Append a spawn-attempt epoch to daemon.spawn-history (ring of the last
    _SPAWN_HISTORY_KEEP entries). The history is what _crash_loop_active counts;
    the single daemon.spawn-attempt.ts marker stays as the fine-grained throttle."""
    ts = int(now if now is not None else time.time())
    path = _spawn_history_path()
    lines: list[str] = []
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip().isdigit()]
    except (FileNotFoundError, OSError):
        lines = []
    lines.append(str(ts))
    state.atomic_write(path, "\n".join(lines[-_SPAWN_HISTORY_KEEP:]))


def _crash_loop_active(now: Optional[int] = None) -> bool:
    """True iff _CRASH_LOOP_SPAWN_LIMIT or more spawn attempts landed within the
    last _CRASH_LOOP_WINDOW_S — the daemon is dying on start; stop feeding it.
    Self-draining: while active no new attempts are recorded, so entries age out
    of the window and spawning resumes on its own. Unreadable history → False
    (never block a spawn on a corrupt bookkeeping file)."""
    ts = int(now if now is not None else time.time())
    try:
        raw = _spawn_history_path().read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return False
    recent = [ln for ln in raw.splitlines()
              if ln.strip().isdigit() and ts - int(ln.strip()) <= _CRASH_LOOP_WINDOW_S]
    return len(recent) >= _CRASH_LOOP_SPAWN_LIMIT


# ---------- C4 (TRDD-T198DT1W) — public read-only crash-loop signal ----------
#
# C4 (bad-self-update auto-rollback) needs to ANSWER "is the daemon dying on
# every start?" from OUTSIDE this module — the dispatch heartbeat reads it to
# decide whether to quarantine the crash-looping newest version (so the
# dispatcher-stub's C3 quarantine-skip falls back to a known-good older one).
# These are thin, READ-ONLY views over the EXISTING spawn-history breaker
# (`_crash_loop_active` / `daemon.spawn-history`); they record nothing, mutate
# nothing, and change no spawn behavior — they only EXPOSE the signal the
# breaker already computes, so dispatch never reaches into a `_`-private. Both
# fail-open (an unreadable history reads as "not crash-looping" / count 0), so
# C4 never quarantines on a bookkeeping fault.


def crash_loop_active(now: Optional[int] = None) -> bool:
    """PUBLIC read-only: True iff the daemon spawn breaker is tripped (the
    daemon is dying on start — ``_CRASH_LOOP_SPAWN_LIMIT`` spawns inside
    ``_CRASH_LOOP_WINDOW_S``). The C4 rollback signal. Pure read; fail-open
    (an unreadable history → False)."""
    return _crash_loop_active(now)


def recent_spawn_count(window_s: Optional[int] = None, now: Optional[int] = None) -> int:
    """PUBLIC read-only: how many daemon spawn attempts landed within the last
    ``window_s`` seconds (default ``_CRASH_LOOP_WINDOW_S``). Diagnostic for C4's
    alert text ("daemon respawned N times"). Pure read; returns 0 on a
    missing/unreadable history (fail-open — C4 never rolls back on count 0)."""
    win = int(window_s if window_s is not None else _CRASH_LOOP_WINDOW_S)
    ts = int(now if now is not None else time.time())
    try:
        raw = _spawn_history_path().read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return 0
    return sum(
        1 for ln in raw.splitlines()
        if ln.strip().isdigit() and ts - int(ln.strip()) <= win
    )


def record_spawn_attempt(now: Optional[int] = None) -> None:
    """PUBLIC: record one daemon spawn attempt into the crash-loop ring.

    The crash-loop breaker (`_crash_loop_active`) only counts attempts written by
    `_record_spawn_attempt`, which is reached ONLY via `spawn_daemon_detached` — the
    SESSION/heartbeat spawn path. An OS-keepalive (launchd/systemd) respawn execs the
    daemon entry directly, never `spawn_daemon_detached`, so an OS-respawned die-on-start
    daemon used to loop forever with an EMPTY spawn-history → `crash_loop_active()` False →
    C4 never quarantined the bad version (KEEPQRTN HIGH-2). The OS-launched daemon calls
    THIS at startup so the OS-driven crash loop becomes visible to the breaker and C4 can
    roll back. Public (not the `_`-private) so `daemon.main()` records without reaching into
    a private. The session path keeps recording via `spawn_daemon_detached` — callers MUST
    record on the OS path ONLY, or the session path would double-count and falsely trip the
    breaker."""
    _record_spawn_attempt(now)


def _kill_wedged_daemon(max_silence_s: int = DEFAULT_DAEMON_STALE_SECONDS) -> bool:
    """Kill a WEDGED daemon — pid alive but heartbeat provably stale — so the kernel
    releases the singleton flock it still holds and a respawn can actually take over.

    Without this, ensure_daemon_running would spawn a replacement that LOSES the
    flock race against the zombie and exits: a silent outage for as long as the
    wedged process lives (the issue-#7 compounding failure mode, second half).

    Safety ladder — every rung must pass before any signal is sent:
      1. never self/parent (per-session tests use os.getpid() as an alive stand-in);
      2. the pid must be alive (a dead pid needs no kill — the spawn path handles it);
      3. the heartbeat must EXIST and be stale beyond max_silence_s (hb==0 could be
         a daemon mid-startup between write_daemon_pid and write_heartbeat — strict
         beats sorry, the plain spawn path covers that case);
      4. the pid's LIVE cmdline must contain "daemon.py" — defends against PID REUSE
         (daemon crashed without cleanup, the OS recycled its pid onto an innocent
         process; killing that would be the exact collateral damage Pillar 4's
         safelist exists to prevent). A foreign cmdline means the real daemon is
         already dead → its flock is already free → no kill needed anyway.

    Escalation: SIGTERM → grace → SIGKILL. A SIGSTOP'd process queues SIGTERM
    without delivering it, so SIGKILL (which works on stopped processes) is the
    only guaranteed terminator for the wedge case. Returns True iff the process
    is gone afterwards. Never raises."""
    import signal as _signal
    pid = daemon_pid()
    if pid is None or pid <= 0 or pid == os.getpid() or pid == os.getppid():
        return False
    if not _process_alive_not_zombie(pid):
        return False  # dead or zombie → flock already free; the spawn path handles it
    hb = read_heartbeat()
    if hb <= 0 or (int(time.time()) - hb) <= max_silence_s:
        return False  # not provably wedged
    cmdline = _read_process_cmdline(pid)
    # BOTH daemon argv shapes are janitor daemons: a session-spawned one runs daemon.py,
    # the launchd/systemd L0 keepalive runs daemon_keepalive_entry.py --keepalive (which
    # does NOT contain the substring "daemon.py"). Matching only the former misclassified
    # a wedged OS-spawned daemon as PID reuse and left it holding the flock forever —
    # launchd respawns on exit, not on hang, so the whole machine lost the daemon.
    if "daemon.py" not in cmdline and "daemon_keepalive_entry.py" not in cmdline:
        state.log_line(
            "daemon",
            f"wedge-kill: pid={pid} heartbeat stale but cmdline {cmdline!r} is not a "
            f"janitor daemon (pid reuse?) — NOT killing; clearing nothing",
        )
        return False
    state.log_line(
        "daemon",
        f"wedge-kill: daemon pid={pid} heartbeat stale {int(time.time()) - hb}s "
        f"(> {max_silence_s}s) — sending SIGTERM",
    )
    try:
        os.kill(pid, _signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return not _process_alive_not_zombie(pid)
    deadline = time.time() + _WEDGE_TERM_GRACE_S
    while time.time() < deadline:
        if not _process_alive_not_zombie(pid):
            state.log_line("daemon", f"wedge-kill: pid={pid} exited on SIGTERM")
            return True
        time.sleep(0.1)
    # Still alive (a SIGSTOP'd wedge never delivers SIGTERM) → escalate.
    state.log_line("daemon", f"wedge-kill: pid={pid} survived SIGTERM — escalating to SIGKILL")
    try:
        os.kill(pid, _signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        return not _process_alive_not_zombie(pid)
    deadline = time.time() + _WEDGE_KILL_GRACE_S
    while time.time() < deadline:
        if not _process_alive_not_zombie(pid):
            break
        time.sleep(0.1)
    gone = not _process_alive_not_zombie(pid)
    state.log_line(
        "daemon",
        f"wedge-kill: pid={pid} {'killed' if gone else 'STILL ALIVE after SIGKILL (foreign uid?)'}",
    )
    return gone


def ensure_daemon_running(max_silence_s: int = DEFAULT_DAEMON_STALE_SECONDS) -> bool:
    """If the daemon is dead AND not kill-switched AND enabled, spawn it.

    Cheap (file stat + one syscall) when the daemon is already alive — safe
    to call at the top of every heartbeat fire. Returns the post-call best-
    estimate of liveness:
      * True when the daemon was already alive.
      * True when we spawned successfully (the child may still be racing the
        flock, but a spawn was issued).
      * False when the kill switch is set, the master `daemon_enabled` knob
        is off, the spawn could not happen, the spawn was throttled because a
        previous attempt is still within the min-spawn window, OR the crash-loop
        breaker is tripped (too many spawn attempts inside the window).

    Pillar 0 (TRDD-7100178d): before spawning, a WEDGED daemon (pid alive,
    heartbeat stale — still holding the singleton flock) is killed via
    `_kill_wedged_daemon` so the replacement can actually acquire the flock.

    The master switch is `CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED` (truthy by
    default). When false, the daemon is never lazy-spawned AND every
    per-session shim becomes a silent no-op (the shims call us first; we
    return False, they exit).

    Spawn throttle: daemon.spawn-attempt.ts (stamped by spawn_daemon_detached)
    gates re-spawns to one per _DEFAULT_MIN_SPAWN_INTERVAL_SECONDS. This is the
    backoff that stops a die-on-start daemon from being re-spawned by every
    heartbeat fire of every session.
    """
    if kill_switch_present():
        return False
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED", True):
        return False
    if daemon_is_alive(max_silence_s=max_silence_s):
        return True
    # Pillar 0 (TRDD-7100178d Phase 4): not-alive splits into DEAD (pid gone — the
    # spawn below just works) and WEDGED (pid alive, heartbeat stale — it still HOLDS
    # the singleton flock, so a plain respawn would lose the flock race against the
    # zombie and exit: a silent outage for as long as the wedge lives). Kill the
    # wedged process first (cmdline-verified, SIGTERM→SIGKILL) so the kernel frees
    # the flock and the spawn can actually take over. No-ops fast in the DEAD case.
    _kill_wedged_daemon(max_silence_s=max_silence_s)
    # Crash-loop circuit-breaker: a daemon dying on EVERY start would otherwise be
    # re-fed once per throttle window forever. Refuse to spawn while the breaker is
    # tripped; it self-resets as attempts age out of the window.
    if _crash_loop_active():
        state.log_line(
            "daemon",
            f"spawn refused — crash-loop breaker tripped ({_CRASH_LOOP_SPAWN_LIMIT}+ "
            f"attempts in {_CRASH_LOOP_WINDOW_S}s); will retry once attempts age out",
        )
        return False
    # Throttle: refuse to re-spawn if the last attempt is still within the
    # min-spawn window. Reads the marker spawn_daemon_detached already writes,
    # closing the "written-but-never-read" gap that allowed unbounded respawn
    # churn when the daemon dies on start.
    min_interval = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_DAEMON_MIN_SPAWN_INTERVAL"),
        _DEFAULT_MIN_SPAWN_INTERVAL_SECONDS,
    )
    last_attempt = state.read_int_state(_spawn_marker_path(), 0)
    if last_attempt and (int(time.time()) - last_attempt) < min_interval:
        return False
    spawn_daemon_detached()
    return True
