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
from typing import Iterator, Optional, Tuple

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
    return Path.home() / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins" / "global-state"


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


# ---------- fixed CONTROL-PLANE directory (ARCHITECTURE.md §7.1, TRDD-QK7M2B0X) -----
#
# The six MODE flags below (kill-switch, maintenance, global-pause, the two reload
# generations, version-update-request) must be readable by an EXTERNAL program that
# knows nothing about this plugin's internals — the ai-maestro server, run under pm2,
# with no fixed install location of its own ("wherever the user installs ai-maestro").
# global_state_dir()'s 4-rung ladder (env override -> XDG -> DATA dir once migrated ->
# legacy) is exactly what such a reader cannot reproduce: hardcoding any one rung reads
# the WRONG file whenever a different rung actually applies, and the failure is SILENT
# (a missing flag just reads as "not set", never an error). So these six flags move to
# ONE fixed, un-resolved path any external consumer can hardcode and `stat()`.


def control_dir() -> Path:
    """Return the FIXED external control-plane directory: ~/.claude/janitor-control/.

    No ladder, no environment lookup beyond the TEST-ONLY override below — see the
    module comment above for why a foreign reader cannot be handed a resolution ladder.

    Resolved at CALL TIME, never cached as a module-level constant: a frozen
    ``Path.home()`` (or any value computed once at import time) keeps pointing at the
    ORIGINAL $HOME even after a test — or a later re-exec — changes it. That exact bug
    already hit this file once (TRDD-ZNN0UK5K): a cached home path silently kept writing
    outside the redirected test sandbox. Read paths never create this directory; only
    the write helpers below do (mkdir on write, never on read — see
    `_write_flag_provenance`).
    """
    override = os.environ.get("JANITOR_CONTROL_DIR")
    if override:
        return Path(override).expanduser().resolve()
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return Path(home) / ".claude" / "janitor-control"


def _control_path(name: str) -> Path:
    return control_dir() / name


def _old_global_state_path(name: str) -> Path:
    """The pre-control-dir location of a now-relocated flag: `global_state_dir()`
    itself. Kept as a dual-read fallback (TRDD-QK7M2B0X transition window) so a session
    still running the previous release's code — which writes here, not to
    control_dir() — is never silently ignored."""
    return global_state_dir() / name


def _flag_present_dual(name: str) -> bool:
    """Presence check across all THREE locations a control-plane flag may live during
    the migration to control_dir(): the NEW control_dir() (canonical), the OLD
    global_state_dir() path (a not-yet-updated session's writer), and the pre-existing
    janitor-global-state legacy dual-read (TRDD-2U8AH82F, itself already folded into
    old global_state_dir() resolution — checked explicitly here too because
    `_legacy_read_path` only fires while global_state_dir() has flipped past legacy).
    Fail-open: an unreadable directory just reads as "absent", never "blocked"."""
    if _control_path(name).is_file():
        return True
    if _old_global_state_path(name).is_file():
        return True
    legacy = _legacy_read_path(name)
    return legacy is not None and legacy.is_file()


def _flag_clear_dual(name: str) -> None:
    """Remove a control-plane flag from ALL THREE possible locations. A clear that
    only wipes the new path would appear to fail — the old copy still reads as SET via
    `_flag_present_dual` — so every clear sweeps new + old + legacy. Best-effort per
    path: one unwritable location must never stop the others from being cleared."""
    for p in (_control_path(name), _old_global_state_path(name), _legacy_global_state_dir() / name):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _write_flag_provenance(path: Path, reason: str) -> None:
    """Write a control-plane flag's body as one line of provenance JSON:
    ``{"set_at": <epoch>, "by": "<actor>", "pid": <pid>, "reason": "<text>"}``
    (ARCHITECTURE.md §7.1, added after a live incident: a flag was found set on a real
    host with the bare content "maintenance" and no way to determine who wrote it —
    which is how a fleet-wide suppression stayed invisible while the daemon's own
    heartbeat kept advancing). Readers key on PRESENCE ONLY — this body is diagnostic,
    never load-bearing; a reader must never let a malformed body make a present flag
    read back as absent. Atomic (tmp + os.replace) so a reader never observes a
    half-written flag. Creates the parent dir on write (never on read)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    by = f"{os.path.basename(sys.argv[0]) or 'python'}:{os.getpid()}"
    body = json.dumps({"set_at": int(time.time()), "by": by, "pid": os.getpid(), "reason": reason or ""})
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)


def _parse_flag_provenance(path: Path) -> dict:
    """Parse one control-plane flag's provenance body.

    A malformed or legacy body — a pre-JSON bare string like "stopped" /
    "maintenance", or the reload flags' old ``<epoch>\\t<reason>`` tab format — still
    means the flag is SET. This function only degrades the human-readable
    `by`/`set_at`; it must NEVER make a present flag read back as absent (that would
    silently swallow a stop signal). Defaults: set_at=0, by="unknown", pid=0,
    reason="" (or the raw body, best-effort, when nothing structured parses)."""
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        raw = ""
    result: dict = {"set_at": 0, "by": "unknown", "pid": 0, "reason": ""}
    if not raw:
        return result
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        data = None
    if isinstance(data, dict):
        set_at = data.get("set_at")
        result["set_at"] = int(set_at) if isinstance(set_at, (int, float)) and not isinstance(set_at, bool) else 0
        by = data.get("by")
        result["by"] = str(by) if by else "unknown"
        pid = data.get("pid")
        result["pid"] = int(pid) if isinstance(pid, (int, float)) and not isinstance(pid, bool) else 0
        reason = data.get("reason")
        result["reason"] = str(reason) if reason is not None else ""
        return result
    # Legacy `<epoch>\t<reason>` tab format (the reload flags, pre-provenance).
    first_line = raw.splitlines()[0]
    gen_tok, _, reason_tok = first_line.partition("\t")
    gen_tok = gen_tok.strip()
    if gen_tok.isdigit():
        result["set_at"] = int(gen_tok)
        result["reason"] = reason_tok.strip()
        return result
    # Legacy bare-text body ("stopped", "maintenance", ...) — still SET, just with no
    # timestamp/actor a pre-provenance release ever recorded.
    result["reason"] = raw
    return result


def read_flag_provenance(name: str) -> dict:
    """Read one control-plane flag's provenance, checking the same THREE locations
    `_flag_present_dual` checks, newest-canonical-location-first. Returns the
    unknown-defaults dict (set_at=0, by="unknown", pid=0, reason="") when the flag is
    absent everywhere — callers key on presence via the dedicated `*_present()`
    functions; this is for diagnostics/CLI display only."""
    for candidate in (_control_path(name), _old_global_state_path(name), _legacy_global_state_dir() / name):
        if candidate.is_file():
            return _parse_flag_provenance(candidate)
    return {"set_at": 0, "by": "unknown", "pid": 0, "reason": ""}


def last_run_path(task: str) -> Path:
    """WRITE path for one chore's completion stamp — `control_dir()/<task>.last-run.ts`
    (TRDD-QK7M2B0X phase B step 2, ARCHITECTURE.md §7.1).

    A last-run stamp is coordination data, not private daemon state: it is exactly what a
    SECOND chore owner (a live ai-maestro server) must read to know whether a chore is
    already covered. That audience — not the kind of the data — is what puts it on the
    fixed control plane, where a foreign reader can stat ONE literal path instead of
    reproducing `global_state_dir()`'s four-rung ladder.
    """
    return _control_path(f"{task}.last-run.ts")


def read_last_run(task: str) -> int:
    """One chore's completion epoch, taking the NEWEST across all three eras.

    `max()` is load-bearing, and it is the opposite of the flags' first-found read. During
    the upgrade window a 0.6x daemon still stamps `global_state_dir()` while a new one
    stamps `control_dir()`. First-found on the new path alone would read 0 for a chore that
    just ran, and 0 means "never ran" — so the task is immediately re-run. For
    `marketplace-refresh` that is precisely the duplicated bulk `claude plugin marketplace
    update` that issue #7 exists to prevent, re-introduced by the very move meant to make
    coordination visible. Reading the max cannot make a chore run too EARLY; the worst it
    can do is defer one by up to its own interval.
    """
    best = 0
    for p in (
        _control_path(f"{task}.last-run.ts"),
        _old_global_state_path(f"{task}.last-run.ts"),
        _legacy_global_state_dir() / f"{task}.last-run.ts",
    ):
        try:
            if p.is_file():
                best = max(best, int(p.read_text(encoding="utf-8").strip() or 0))
        except (OSError, ValueError):
            continue  # a corrupt/unreadable stamp must not mask a good one at another path
    return best


def _generation_from_flag(name: str) -> int:
    """Generation number for one of the two reload flags, across all three
    control-plane locations (max() wins — a stamp from ANY era/location still
    triggers exactly one reload). Mirrors the old `_generation_from_file`'s
    "any non-empty legacy body counts as generation 1" fallback, so a bare
    boolean/string body from an even-older release still means "an update
    happened at an unknown time" rather than "absent"."""
    best = 0
    for p in (_control_path(name), _old_global_state_path(name), _legacy_global_state_dir() / name):
        if not p.is_file():
            continue
        prov = _parse_flag_provenance(p)
        gen = prov["set_at"]
        if gen <= 0:
            try:
                gen = 1 if p.read_text(encoding="utf-8").strip() else 0
            except OSError:
                gen = 0
        best = max(best, gen)
    return best


# Files that must NOT be copied by the migration: the kernel locks are dir-bound
# (copying a flock file copies nothing kernel-side, and a stray copy invites a
# split-brain read), and the pid is re-published by the migrating daemon itself.
_MIGRATION_SKIP = frozenset(
    {
        "daemon.flock",
        "daemon.pid",
        "marketplace-op.lock",
        "oauth-rotator-tick.lock",
        # The remaining flocks, for the set's OWN stated reason: the enumeration had simply
        # not caught up with the locks that exist today. Copying a lock file copies zero
        # kernel state, so each copy is an empty decoy at a path a reader can mistake for
        # the live inode. Folded in with the singleton move (TRDD-QK7M2B0X) rather than as
        # a cosmetic edit of its own — migration code is not touched for tidiness.
        "settings-ensurer.lock",
        "ticket-dispatch.lock",
    }
)


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
            f"This janitor state dir was MIGRATED to the plugin DATA dir:\n  {new}\nKept only as a read-fallback for not-yet-updated sessions; safe to\nremove after every session runs a janitor >= the migration release.\n",
            encoding="utf-8",
        )
    return fd


# ---------- file paths (private; callers use the named helpers below) -------


# `daemon.flock` / `daemon.pid` / `daemon.heartbeat.ts` deliberately have NO single-path
# helper. They are the SINGLETON, and the singleton is dual-era for the transition window
# (TRDD-QK7M2B0X phase B step 2) — a helper returning one path could only ever name half
# the truth, and every caller that took that half would silently exclude nobody. Use
# `_singleton_paths` above.


def _killswitch_path() -> Path:
    return _control_path("kill-switch.flag")


def _spawn_marker_path() -> Path:
    return global_state_dir() / "daemon.spawn-attempt.ts"


def _spawn_history_path() -> Path:
    return global_state_dir() / "daemon.spawn-history"


def _reload_flag_path() -> Path:
    return _control_path("reload-needed.flag")


def _skills_reload_flag_path() -> Path:
    return _control_path("skills-reload-needed.flag")


# The three COORDINATION locks live in control_dir() (ARCHITECTURE.md §7.1,
# TRDD-QK7M2B0X phase B). They guard chores a SECOND owner also runs — the ai-maestro
# server absorbs the OAuth pair and the update trio (harness_backend.SERVER_ABSORBED_TASKS)
# — and flock(2) excludes only processes contending on the SAME file, so a lock the server
# cannot find excludes nobody and the §2 collision backstop silently does nothing.
# Each is a BARE FILENAME, not a path: the dual-lock primitive resolves it against BOTH
# control_dir() and the old global_state_dir() for the transition window, so a per-lock
# path helper would only ever name half the truth.
_MARKETPLACE_LOCK = "marketplace-op.lock"
_OAUTH_ROTATOR_LOCK = "oauth-rotator-tick.lock"
_SETTINGS_ENSURER_LOCK = "settings-ensurer.lock"
# PER-PROJECT (not global): the flock filename `detector_lock` places inside a caller's
# `<project>/.janitor/state/` — the single-writer discipline for the daemon-vs-cron race
# (MF3, TRDD-X07E7HTN). Named here beside the other lock filenames for discoverability.
_DETECTOR_LOCK = "detector.lock"


def _ticket_dispatch_lock_path() -> Path:
    # NOT a coordination lock, so it deliberately stays in global_state_dir(): it
    # serialises the janitor's own ticket select→stamp→emit across janitor SESSIONS.
    # No second chore owner ever dispatches a janitor support ticket, and the scope rule
    # for control_dir() is AUDIENCE — publish only what a foreign owner must contend on.
    return global_state_dir() / "ticket-dispatch.lock"


# ---------- singleton sentinels: DUAL-ERA paths (TRDD-QK7M2B0X phase B step 2) -----
#
# `daemon.pid` and `daemon.heartbeat.ts` move to control_dir() with the singleton, and
# that move INVERTS the role the last-run stamps had. For the stamps the writers were OLD
# and the readers NEW, so `read_last_run`'s max() fixed the whole problem from the reading
# side. Here the writer is NEW and the readers are OLD: a 0.6x session's `daemon_is_alive()`
# reads only `global_state_dir()`, finds nothing, concludes DEAD, and spawn-churns against a
# lock it can never take. No reading-side change can reach that session's code — so the new
# writer must DUAL-WRITE, and the new reader dual-reads for the mirror case (an OLD daemon
# that publishes only the old path).
#
# Early signal that the dual-write was dropped or broken: `daemon.spawn-history` filling up
# during an upgrade window.


def _singleton_paths(name: str) -> tuple[tuple[str, Path], ...]:
    """Every era's location for a singleton sentinel as `(era_label, path)`, NEW-first,
    deduped by realpath. ONE list for reading, writing AND locking — deliberately not
    three, because a read set and a write set that disagree is a sentinel published where
    nobody looks.

    Deduping is not tidiness. On a host where two eras resolve to ONE directory (a test
    harness, `$JANITOR_GLOBAL_STATE_DIR`, a forwarding symlink) the same inode would appear
    twice — harmless to read, FATAL to flock, because flock(2) conflicts with itself across
    two open file descriptions in the same process, so the second open would deny us our
    own lock and the daemon would never start (ATOM-QK7M-0002).

    The legacy rung comes from `_legacy_read_path`, which already encodes the whole
    predicate: absent under an explicit `$JANITOR_GLOBAL_STATE_DIR` redirect, absent unless
    the dir ALREADY exists, absent while it is still the resolved `global_state_dir()`.
    Reusing it (rather than re-deriving `legacy / name`) is what stops a WRITE from
    recreating a dir TRDD-2U8AH82F deliberately tombstoned — a resurrected legacy dir is a
    read-fallback the migration retired, and `_legacy_read_path` would start honoring it
    again on a host that never had one.
    """
    out: list[tuple[str, Path]] = []
    seen: set[str] = set()
    candidates: list[tuple[str, Path]] = [
        ("control", _control_path(name)),
        ("global-state", _old_global_state_path(name)),
    ]
    legacy = _legacy_read_path(name)
    if legacy is not None:
        candidates.append(("legacy", legacy))
    for era, path in candidates:
        key = os.path.realpath(str(path))
        if key in seen:
            continue
        seen.add(key)
        out.append((era, path))
    return tuple(out)


def _read_pid_file(path: Path) -> Optional[int]:
    """One era's pid file as an int, or None when missing / unreadable / malformed."""
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return int(raw) if raw.isdigit() else None


def daemon_pid() -> Optional[int]:
    """Read daemon.pid → int, or None if missing / malformed at EVERY era.

    LIVE-PREFERRING across eras, not first-found. During the upgrade window a stale pid can
    sit at one path while the daemon that actually holds the singleton published another;
    first-found would then hand callers a dead pid, `daemon_is_alive()` would say DEAD, and
    every session would try to spawn. The flock still stops the second daemon — that is what
    it is for — but the visible result is spawn→abort churn that fills `daemon.spawn-history`
    and reads exactly like a crash loop, which is how the previous singleton bug hid.
    Preferring a pid that names a LIVE process answers what every caller is really asking.
    When none is live we still return the first one found, so "stale pid file" stays
    distinguishable from "no pid file at all".
    """
    first: Optional[int] = None
    for _, path in _singleton_paths("daemon.pid"):
        pid = _read_pid_file(path)
        if pid is None:
            continue
        if first is None:
            first = pid
        if _process_exists(pid):
            return pid
    return first


def write_daemon_pid(pid: int) -> None:
    """Publish the daemon's pid at EVERY era's path (see the dual-write note above)."""
    value = str(int(pid))
    for _, path in _singleton_paths("daemon.pid"):
        try:
            state.atomic_write(path, value)
        except OSError:
            continue  # one unwritable era must never stop the canonical one


def remove_daemon_pid() -> None:
    """Clear the pid from every era. A clear that missed one would leave a shutdown daemon
    still advertising itself to whichever reader resolves that path."""
    for _, path in _singleton_paths("daemon.pid"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # Best-effort cleanup; the next daemon will overwrite anyway.
            pass


def write_heartbeat(now: Optional[int] = None) -> None:
    """Stamp the liveness beat at EVERY era's path (see the dual-write note above)."""
    value = str(int(now if now is not None else time.time()))
    for _, path in _singleton_paths("daemon.heartbeat.ts"):
        try:
            state.atomic_write(path, value)
        except OSError:
            continue


def read_heartbeat() -> int:
    """The NEWEST liveness beat across every era.

    max(), for `read_last_run`'s reason plus a sharper one: during the window a 0.6x daemon
    beats only at `global_state_dir()`, so a new-path-only read returns 0 — and 0 means "no
    heartbeat", i.e. DEAD. Every new session would then try to spawn a second daemon against
    a perfectly healthy old one. max() cannot invent liveness: a stale file stays stale
    against `now`, and only a LIVE daemon can write a recent beat anywhere.
    """
    best = 0
    for _, path in _singleton_paths("daemon.heartbeat.ts"):
        best = max(best, state.read_int_state(path, 0))
    return best


def foreign_era_daemons(self_pid: Optional[int] = None) -> list[tuple[str, int]]:
    """Every era whose `daemon.pid` names a LIVE process that is not `self_pid`.

    The dual-lock below closes the window that would let two daemons coexist — but
    "closed by construction" is a claim, and an unverified claim about a singleton is
    precisely how the two-daemon bug hid the first time. This is the detector. It costs one
    stat plus one `kill(pid, 0)` per era per tick and converts a silent double-daemon into
    an indexed finding. Returns `[(era_label, pid), …]`, empty on a healthy host.
    """
    me = int(self_pid) if self_pid is not None else os.getpid()
    out: list[tuple[str, int]] = []
    seen: set[int] = set()
    for era, path in _singleton_paths("daemon.pid"):
        pid = _read_pid_file(path)
        if pid is None or pid == me or pid in seen:
            continue
        seen.add(pid)
        if _process_exists(pid):
            out.append((era, pid))
    return out


def kill_switch_present() -> bool:
    # Triple-read (TRDD-QK7M2B0X + TRDD-2U8AH82F): a fleet STOP set at control_dir()
    # (canonical), the pre-control-dir global_state_dir() location, or the legacy
    # janitor-global-state path must still be honored across every writer era.
    return _flag_present_dual("kill-switch.flag")


def set_kill_switch(reason: str = "") -> None:
    """Create the kill-switch flag — the machine-wide STOP (TRDD-56d24c02 follow-up).
    The running daemon sees it on its next loop and exits, AND ``ensure_daemon_running``
    stops lazy-spawning it — so a deliberate stop is NOT resurrected by either path.
    ``/janitor-global-arm`` clears it to revive. Written atomically at control_dir()
    (ARCHITECTURE.md §7.1, TRDD-QK7M2B0X) with a provenance body; readers key on
    presence, never on the body's content."""
    _write_flag_provenance(_killswitch_path(), reason or "stopped")


def clear_kill_switch() -> None:
    """Remove the kill-switch flag from every location it may live (control_dir(), the
    pre-control-dir global_state_dir(), and the legacy dir) so the daemon can be
    lazy-spawned again — the revive half of the disarm/arm pair. Idempotent (a missing
    flag anywhere is fine)."""
    _flag_clear_dual("kill-switch.flag")


def clear_maintenance_mode() -> None:
    """Clear a RETIRED machine-wide MAINTENANCE flag from every location it may live.

    Maintenance mode is gone (owner directive 2026-07-31 — the ruling that also removed pause
    and `keep-going-off`). It kept every session's cron firing and the daemon resident while
    doing none of the work, so a quiesced fleet looked exactly like a healthy one from a
    process list, a cron list, or a daemon heartbeat. Only the CLEAR survives, and only as a
    migration: nothing reads the flag any more, but a host that was in maintenance when it
    last ran an older janitor still has it on disk, and leaving it there tells the next
    person to read the control plane that the machine is suspended. `arm` sweeps it. Removed
    once no supported version can have set it."""
    _flag_clear_dual("maintenance-mode.flag")


def clear_global_pause() -> None:
    """Clear a RETIRED machine-wide PAUSE flag from every location it may live.

    The pause switch is gone (owner directive 2026-07-31 — see `dispatch._phase_keep_going_nudge`
    for the incident). Only the CLEAR survives, and only as a migration: a host that was paused
    when it last ran an older janitor still has the flag on disk, and while nothing reads it any
    more, leaving it there means the next person to look at the control plane sees a machine that
    claims to be paused. Every arm sweeps it. Removed once no supported version can have set it."""
    _flag_clear_dual("global-pause.flag")


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
# (daemon) are new — there is no version-skew writer at the legacy path to miss. It is
# still ONE of the six flags moved to control_dir() (ARCHITECTURE.md §7.1,
# TRDD-QK7M2B0X): the ai-maestro server, not only the daemon, may want to raise it.


def _version_update_request_path() -> Path:
    return _control_path("version-update-requested.flag")


def version_update_requested_present() -> bool:
    """True iff a session detector (or an external control-plane writer) has requested
    an immediate janitor self-update (TRDD-Y9KM5RCJ). The daemon checks this each loop
    and, when set, runs the version-update task NOW rather than waiting for the 6 h beat.
    Dual-read across control_dir() and the pre-control-dir global_state_dir() location."""
    return _flag_present_dual("version-update-requested.flag")


def request_version_update(reason: str = "") -> None:
    """Raise the release-triggered self-update request at control_dir() (ARCHITECTURE.md
    §7.1, TRDD-QK7M2B0X). Idempotent (re-writing the same flag is harmless; the daemon
    clears it on consume). Written atomically with a provenance body. Best-effort — a
    write failure just falls back to the 6 h beat (fail-open), so this never crashes the
    read-only detector that calls it."""
    try:
        _write_flag_provenance(_version_update_request_path(), reason or "requested")
    except OSError:
        pass


def clear_version_update_request() -> None:
    """Clear the release-triggered self-update request from every location it may live.
    The daemon calls this BEFORE running the update (clear-before-run: a run that fails
    is re-signalled by the detector's next ~5 min fire, never lost to a
    clear-after-run crash). Idempotent."""
    _flag_clear_dual("version-update-requested.flag")


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
        fd = os.open(str(global_state_dir() / "plugin-update-requests.lock"), os.O_RDWR | os.O_CREAT, 0o644)
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
    """``"disarm"`` iff the machine-wide kill-switch is set, else None.

    It used to also return ``"pause"`` for the softer global-pause flag. Pause is gone with the
    rest of the off-switches (owner directive 2026-07-31): a stop that leaves the daemon alive but
    idle is precisely the silent-disable shape that caused the incident — indistinguishable, from
    the outside, from a healthy fleet. Disarm remains because it is loud and total: the cron is
    deleted, so a disarmed session cannot be mistaken for a working one."""
    return "disarm" if kill_switch_present() else None


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


# ---------- transitional DUAL-LOCK primitive (TRDD-QK7M2B0X phase B) ------
#
# Moving a coordination lock is not the same problem as moving a flag, and the
# difference is the whole reason this primitive exists.
#
# A flag is data: a reader that probes the new path AND the old one cannot miss it, so
# `_flag_present_dual` is enough. A flock is not data — it is kernel state attached to an
# INODE. During the upgrade window a 0.61 session locking only ~/.claude/janitor-control/
# and a 0.60 session locking only global_state_dir() each acquire successfully and each
# believes it is the machine's single writer. That is not a missed signal, it is the exact
# concurrent `claude plugin marketplace update` / rotator double-tick these locks were
# built to prevent (issue #7). "Dual-read" has no meaning here; the transition has to be a
# dual-LOCK, held on BOTH inodes for the same critical section.
#
# Order is fixed NEW-then-OLD everywhere. With non-blocking acquisition that ordering
# cannot deadlock (a loser releases what it holds and skips), and keeping it uniform means
# two new-code peers always contend on the new inode first — so the old path can never
# become the deciding lock between two processes that both understand the new one.
#
# Retire this with the rest of the transitional fallbacks two releases out (TRDD step 5):
# drop the OLD half and the tuple collapses back to a single fd.

LockHandle = Tuple[int, ...]


# Paths already reported as unopenable, so the finding is filed at most ONCE per process
# per path. The daemon retries every tick, and an append-only ledger growing by a line a
# tick is its own outage — the boundedness invariant (TRDD-7IUTRX29 S3/S4) applies to
# alarms exactly as it does to self-heals.
_CONTROL_UNWRITABLE_REPORTED: set[str] = set()


def _report_control_dir_unwritable(path: Path, exc: BaseException, log_channel: str) -> None:
    """A coordination file under `control_dir()` could not even be OPENED — file a FINDING.

    `_try_flock` treats an unopenable lock as HELD, which is the only safe reading: a caller
    without the lock has no exclusion. But applied to the control plane, that safety becomes
    a silent shutdown — an unwritable `~/.claude/janitor-control/` makes every coordination
    lock unavailable AND the daemon singleton unacquirable, so the daemon never starts and
    nothing anywhere says why. That is the exact looks-fine-ignores-the-control-plane failure
    this directory was created to END, so it gets an indexed finding rather than a log line
    a human would have to already suspect something to go looking for.
    """
    key = str(path)
    if key in _CONTROL_UNWRITABLE_REPORTED:
        return
    _CONTROL_UNWRITABLE_REPORTED.add(key)
    state.log_line(log_channel, f"control plane UNWRITABLE at {path}: {exc}")
    try:
        import findings_ledger  # local import: keeps the ledger off every hook's import path

        findings_ledger.record(
            sev="HIGH",
            code="CONTROL-DIR-UNWRITABLE",
            src="global-state",
            msg=(
                f"control plane unusable ({path.name}): {exc.__class__.__name__} — "
                "the daemon and every coordination lock are blocked"
            ),
        )
    except Exception:  # noqa: BLE001 — a finding that cannot be filed must never break locking
        pass


def _try_flock(path: Path, *, log_channel: str, blocking: bool = False) -> Optional[int]:
    """Open `path` (creating it) and take an exclusive flock.

    Returns the fd on success, or None when the lock is unavailable — whether because
    another process holds it (EAGAIN, the ordinary skip path) or because the file could
    not be opened at all. An unopenable lock file is reported and then treated as HELD,
    never as free: a caller that cannot take the lock has no exclusion, and running the
    chore anyway is the corruption this module exists to prevent. When the unopenable path
    is on the CONTROL PLANE the report is an indexed finding, not just a log line — see
    `_report_control_dir_unwritable`.

    `blocking=True` WAITS instead of skipping. Only the singleton uses it (the OS-keepalive
    daemon, which would otherwise busy-loop spawn→abort→respawn under launchd KeepAlive);
    every chore lock stays non-blocking, where a loser skipping its turn is deadlock-proof
    and costs at most one cadence.
    """
    try:
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as exc:
        if _same_file(path.parent, control_dir()):
            _report_control_dir_unwritable(path, exc, log_channel)
        else:
            state.log_line(log_channel, f"cannot open lock file {path}: {exc} — treating as held")
        return None
    lock_op = fcntl.LOCK_EX if blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        while True:
            try:
                fcntl.flock(fd, lock_op)
                return fd
            except InterruptedError:
                # A signal interrupted a BLOCKING wait → retry. Non-blocking never blocks,
                # so it cannot raise this; if it somehow does, fall through to the error path.
                if blocking:
                    continue
                raise
    except (BlockingIOError, OSError) as exc:
        try:
            os.close(fd)
        except OSError:
            pass
        if isinstance(exc, BlockingIOError) or getattr(exc, "errno", None) in (errno.EAGAIN, errno.EWOULDBLOCK):
            return None
        # Unexpected — surface to logs but don't crash the caller.
        state.log_line(log_channel, f"unexpected flock error on {path.name}: {exc}")
        return None


def _same_file(a: Path, b: Path) -> bool:
    """True iff both paths name the same file on disk, symlinks resolved. `realpath` (not
    `samefile`) because it answers even when one side does not exist yet, and never
    raises."""
    return os.path.realpath(str(a)) == os.path.realpath(str(b))


def _acquire_dual_flock(name: str, *, log_channel: str) -> Optional[LockHandle]:
    """Take coordination lock `name` on BOTH the new control_dir() path and the old
    global_state_dir() one, in that order. Returns an opaque handle to pass to
    `_release_dual_flock`, or None when EITHER path is unavailable — a partial hold
    excludes only half the fleet, so the half we could take is released immediately and
    the caller skips this round exactly as it would for any other contended lock.
    """
    control = control_dir()
    try:
        control.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        state.log_line(log_channel, f"cannot create control dir {control}: {exc} — skipping {name}")
        return None
    init_global_state()
    new_path = control / name
    new_fd = _try_flock(new_path, log_channel=log_channel)
    if new_fd is None:
        return None
    old_path = _old_global_state_path(name)
    if _same_file(new_path, old_path):
        # One inode, two names — a config (or a test harness) that points both dirs at the
        # same place, or an old path symlinked forward. Opening it a second time would
        # DENY US OUR OWN LOCK: flock(2) conflicts across independent open file
        # descriptions even inside one process, so the "dual" hold would self-deadlock and
        # the chore would skip forever while looking merely contended. One inode needs
        # exactly one lock — and it already excludes both eras.
        return (new_fd,)
    old_fd = _try_flock(old_path, log_channel=log_channel)
    if old_fd is None:
        _release_dual_flock((new_fd,))
        return None
    return (new_fd, old_fd)


def _release_dual_flock(handle: LockHandle) -> None:
    """Release every fd in a handle from `_acquire_dual_flock`. Best-effort per fd: one
    failing unlock must never leak the others (the kernel frees them on close anyway)."""
    for fd in handle:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass


# ---------- the DAEMON SINGLETON, dual-era (TRDD-QK7M2B0X phase B step 2) ------------
#
# The singleton needs its OWN primitive and CANNOT call `_acquire_dual_flock`. That one
# RELEASES both halves on partial failure, which is right for a chore lock (skip this
# round, the cadence brings you back in 20 minutes) and wrong here: the singleton must be
# able to HOLD the new lock ACROSS the retirement of the old one — TRDD-2U8AH82F's
# flock-moves-LAST invariant, which is also exactly what `migrate_global_state_to_data_dir`
# does one step later in daemon startup.
#
# Order is NEW-then-OLD, as everywhere else in this module, and being TOTAL it cannot
# deadlock even in the blocking variant: every participant queues on the same inode first.
#
# The asymmetry that justifies spelling all this out: a mode flag moved at a bad moment
# costs ONE duplicated chore. A flock moved at a bad moment costs a SECOND DAEMON — on a
# host that may already be running an ai-maestro server.


def acquire_singleton_dual(*, blocking: bool = False) -> Optional[LockHandle]:
    """Acquire the daemon singleton on EVERY era's `daemon.flock`, NEW path first.

    Returns an opaque handle the caller MUST keep alive for the daemon's lifetime (closing
    any fd releases that half), or None when ANY era is unavailable — a partial hold
    excludes only part of the fleet, which is indistinguishable from no singleton at all,
    so the loser releases what it took and exits.

    Default `blocking=False`: a session-spawned daemon that loses the race just aborts.

    `blocking=True`: WAIT rather than abort. This is for the OS-keepalive (L0) daemon under
    launchd/systemd KeepAlive, which would otherwise be respawned immediately and busy-loop
    spawn→abort→respawn every ThrottleInterval while a session-spawned daemon holds the
    singleton. Blocking makes it idle at zero churn until the holder exits (TRDD-71ABD7V7).
    Safe to interrupt: while blocked it has not written its pid or installed handlers, so a
    bootout SIGTERM kills it cleanly with nothing to unwind.

    The flock — not the pid file, not the heartbeat — is the truth about "is a daemon alive
    RIGHT NOW". Those two are diagnostics; only the kernel's lock state actually excludes.
    """
    control = control_dir()
    try:
        control.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _report_control_dir_unwritable(control / "daemon.flock", exc, "daemon")
        return None
    init_global_state()
    fds: list[int] = []
    for _, path in _singleton_paths("daemon.flock"):
        fd = _try_flock(path, log_channel="daemon", blocking=blocking)
        if fd is None:
            _release_dual_flock(tuple(fds))
            return None
        fds.append(fd)
    return tuple(fds)


def release_singleton_dual(handle: LockHandle) -> None:
    """Release every era's singleton flock. Best-effort — the kernel frees them on process
    death regardless, so a double release or a stale fd is harmless."""
    _release_dual_flock(handle)


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


def acquire_marketplace_lock() -> Optional[LockHandle]:
    """Non-blocking exclusive flock on marketplace-op.lock.

    Return an OPAQUE handle on success — the caller MUST pass it back to
    release_marketplace_lock() once the marketplace operation finishes, and MUST NOT
    interpret it (it is the dual-lock tuple for the control_dir() transition, not a bare
    fd). Return None when another process already holds it; the caller MUST then SKIP the
    marketplace operation this round (never block on it).
    """
    return _acquire_dual_flock(_MARKETPLACE_LOCK, log_channel="daemon")


def release_marketplace_lock(handle: LockHandle) -> None:
    """Release the marketplace-op flock and close its fds. Best-effort."""
    _release_dual_flock(handle)


@contextlib.contextmanager
def ticket_dispatch_lock() -> Iterator[bool]:
    """Serialise the support-ticket select→stamp→emit against every other session (TRDD-CGYMUKO6).

    Its OWN lock, deliberately not the marketplace one: two sessions firing the same heartbeat window
    would otherwise both select the same ticket and both spawn a repair agent for it. Skip-if-held —
    the loser stays silent this fire, and by then the winner has already moved the tickets to
    `dispatched`, so the loser no longer sees them as due (the same convergence the memory scheduler
    relies on).

        with gs.ticket_dispatch_lock() as held:
            if not held:
                return 0        # another session is dispatching this window
    """
    init_global_state()
    fd: Optional[int] = None
    try:
        fd = os.open(str(_ticket_dispatch_lock_path()), os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
            fd = None
    try:
        yield fd is not None
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
    handle = acquire_marketplace_lock()
    try:
        yield handle is not None
    finally:
        if handle is not None:
            release_marketplace_lock(handle)


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


def acquire_oauth_rotator_lock() -> Optional[LockHandle]:
    """Non-blocking exclusive flock on oauth-rotator-tick.lock.

    Return an OPAQUE handle on success — the caller MUST pass it back to
    release_oauth_rotator_lock() once the rotator tick finishes, and MUST NOT interpret
    it (see acquire_marketplace_lock). Return None when another process already holds it;
    the caller MUST then SKIP the tick this round (never block on it).
    """
    return _acquire_dual_flock(_OAUTH_ROTATOR_LOCK, log_channel="daemon")


def release_oauth_rotator_lock(handle: LockHandle) -> None:
    """Release the oauth-rotator-tick flock and close its fds. Best-effort."""
    _release_dual_flock(handle)


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
    handle = acquire_oauth_rotator_lock()
    try:
        yield handle is not None
    finally:
        if handle is not None:
            release_oauth_rotator_lock(handle)


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
    handle = acquire_oauth_rotator_lock()
    while handle is None and time.time() < deadline:
        time.sleep(poll_s)
        handle = acquire_oauth_rotator_lock()
    try:
        yield handle is not None
    finally:
        if handle is not None:
            release_oauth_rotator_lock(handle)


# ---------- settings-ensurer lock ----------------------------------------
#
# Serialises the per-session settings-ensurer's read-merge-write of the SINGLE
# shared user file ~/.claude/settings.json across concurrent Claude Code sessions
# (each SessionStart hook runs the ensurer). Idempotency already prevents key loss
# — every janitor writer adds the SAME keys and enforces the SAME target value, so
# last-writer-wins converges — but a shared lock removes the write-write race
# outright and guards any future non-idempotent change. Non-blocking BY DESIGN: a
# loser SKIPS (another session is already applying the identical settings), so a
# heartbeat/session-start turn never blocks. It cannot protect against a NON-janitor
# writer (the user's editor); the ensurer's only-write-on-delta window + the atomic
# os.replace cover that (never a torn file).


def acquire_settings_ensurer_lock() -> Optional[LockHandle]:
    """Non-blocking exclusive flock on settings-ensurer.lock.

    Return an OPAQUE handle on success (caller MUST pass it back to
    release_settings_ensurer_lock and MUST NOT interpret it — see
    acquire_marketplace_lock), or None when another process holds it — the caller MUST
    then SKIP (never block).
    """
    return _acquire_dual_flock(_SETTINGS_ENSURER_LOCK, log_channel="session-start")


def release_settings_ensurer_lock(handle: LockHandle) -> None:
    """Release the settings-ensurer flock and close its fds. Best-effort."""
    _release_dual_flock(handle)


@contextlib.contextmanager
def settings_ensurer_lock() -> Iterator[bool]:
    """Serialise a settings-ensurer write against every other session's ensurer.

    Yields True when the lock was acquired (apply the settings), or False when another
    session holds it (SKIP — it is applying the identical settings). Releases on exit.
    """
    handle = acquire_settings_ensurer_lock()
    try:
        yield handle is not None
    finally:
        if handle is not None:
            release_settings_ensurer_lock(handle)


# ---------- per-project detector single-writer lock ----------------------
#
# A PER-PROJECT flock (`<project>/.janitor/state/detector.lock`) that serialises any
# `.janitor/state` mutation the daemon and the fallback cron could BOTH perform, so the
# two never race / double-write / corrupt dedupe (MF3, TRDD-X07E7HTN). Unlike every lock
# above — which is machine-global, in `global_state_dir()` / `control_dir()` — this one is
# scoped to ONE project, so its path is a caller-supplied state dir, and it is a SINGLE
# flock (there is no legacy-migration second mouth to hold, unlike the control-dir locks).
#
# In v1 the daemon writes ONLY the resume wake-dedupe + coverage stamps under it, runs NO
# detector, and touches NO `last-run-*.ts` / seen-file — the lock is specified now purely so
# the future full-roster scope (a daemon that runs detectors) is single-writer-safe from day
# one. Non-blocking BY DESIGN: a loser SKIPS this round. The daemon re-fires every liveness
# interval and the cron on its own cadence, so a skip is always safe and never wedges a
# heartbeat turn behind the other writer.


@contextlib.contextmanager
def detector_lock(state_dir: Path) -> Iterator[bool]:
    """Serialise a per-PROJECT `.janitor/state` mutation against the other writer (MF3).

    Yields True when the flock on `<state_dir>/detector.lock` was acquired (safe to write),
    or False when the other writer (daemon or cron) holds it (SKIP this round). Releases on
    exit iff held. Never raises — a mkdir/open failure degrades to "not held" (skip), so a
    lock fault can never crash the beat that consulted it.

        with gs.detector_lock(sd) as held:
            if not held:
                return   # the other writer holds it this round
    """
    fd: Optional[int] = None
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(state_dir / _DETECTOR_LOCK), os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
            fd = None
    try:
        yield fd is not None
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


# ---------- spawn ---------------------------------------------------------


def daemon_script_path() -> Path:
    """Resolve scripts/daemon.py absolute path.

    The detectors and dispatch live under scripts/; this module is under
    scripts/lib/. Walking one parent up from __file__'s dir gets us scripts/.
    """
    return Path(__file__).resolve().parent.parent / "daemon.py"


# TRDD-DB1P25S4: the python version the janitor pins everywhere (uv venv, CI, the
# owner's granted interpreter). `_managed_python_path` resolves uv's MANAGED CPython
# for this pin — the FIXED-path interpreter a macOS TCC Automation grant can stick to.
_MANAGED_PYTHON_PIN = "3.12"


def _managed_python_path() -> Optional[str]:
    """Absolute path of uv's MANAGED CPython for the pinned version, or None.

    WHY (TRDD-DB1P25S4 / GH#92): macOS TCC persists an Automation grant against a
    STABLE client identity. `uv run --script` mints an EPHEMERAL
    `~/.cache/uv/builds-v0/.tmpXXXX/bin/python` shim — a NEW binary path on every
    respawn — so no grant can ever attach to the same client twice, and the daemon's
    osascript fleet scans trip the iTerm-denial alarm forever. uv's MANAGED
    interpreter (`~/.local/share/uv/python/cpython-<pin>.../bin/python3.12`) never
    moves, which is why the owner's grant sticks to it. Both daemon spawn paths (this
    session-side one and the launchd plist baked by
    keepalive_install.sh::resolve_interpreter) must therefore prefer it.

    `--system` is LOAD-BEARING: without it, `uv python find` run from inside a
    project returns that project's `.venv/bin/python3` (measured), a cwd-dependent
    identity that defeats the whole point. `--managed-python` restricts the search
    to uv-managed installs; when none matches the pin the command exits non-zero and
    we return None (find never downloads anything).
    """
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["uv", "python", "find", "--system", "--managed-python", _MANAGED_PYTHON_PIN],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    out = (proc.stdout or "").strip()
    if not out:
        return None
    path = out.splitlines()[-1].strip()
    if path and os.path.isfile(path) and os.access(path, os.X_OK):
        return path
    return None


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

    Interpreter choice (TRDD-DB1P25S4): prefer uv's MANAGED CPython so the daemon —
    and every osascript child it spawns, since its children inherit
    `sys.executable` — carries the STABLE binary identity the user's TCC Automation
    grant is attached to. `uv run --script` is only the fallback: it mints an
    ephemeral, ungrantable python shim per spawn (see `_managed_python_path`). The
    daemon's import closure is stdlib-only BY DESIGN (keepalive staging), so plain
    python runs it unchanged; uv was ever only a launcher convenience.
    """
    init_global_state()
    state.atomic_write(_spawn_marker_path(), str(int(time.time())))
    _record_spawn_attempt()  # crash-loop bookkeeping (Pillar 0) — every spawn path counts
    script = daemon_script_path()
    if not script.is_file():
        state.log_line("daemon", f"daemon script missing at {script} — cannot spawn")
        return None
    candidates: list[list[str]] = []
    managed = _managed_python_path()
    if managed:
        candidates.append([managed, str(script)])
    # `uv run --script` still resolves the PEP 723 header on hosts without a managed
    # 3.12; plain `sys.executable` is the last resort (the daemon detects and logs
    # missing deps itself — its closure declares none).
    candidates.append(["uv", "run", "--script", "--quiet", str(script)])
    candidates.append([sys.executable, str(script)])
    for cmd in candidates:
        try:
            proc = subprocess.Popen(  # noqa: S603 - explicit args, no shell
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
            return proc.pid
        except OSError as exc:  # FileNotFoundError included — try the next launcher
            state.log_line("daemon", f"spawn via {cmd[0]} failed: {exc}")
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


def reload_generation() -> int:
    """Return the reload generation (epoch the daemon last stamped after a
    plugin changed on disk), or 0 if none. NEVER mutated by a reader. Reads the
    provenance body's `set_at` (current JSON format) or the legacy
    `<epoch>\\t<reason>` tab format (pre-provenance), across control_dir(), the
    pre-control-dir global_state_dir() location, and the legacy dir
    (TRDD-QK7M2B0X + TRDD-2U8AH82F) — max() wins, so a stamp from any era or
    location still triggers exactly one reload."""
    return _generation_from_flag("reload-needed.flag")


def reload_flag_present() -> bool:
    return reload_generation() > 0


def set_reload_flag(reason: str = "") -> None:
    """Stamp the reload generation (current epoch) at control_dir() (ARCHITECTURE.md
    §7.1, TRDD-QK7M2B0X) after a plugin changed on disk. Body is the provenance JSON
    (`set_at` carries the generation each session compares against its per-project
    ack). Monotonic (wall-clock only advances) and NEVER cleared by a reader —
    clearing is precisely what starved concurrent sessions in the old single-flag
    design."""
    _write_flag_provenance(_reload_flag_path(), reason)


def clear_reload_flag() -> None:
    """Reset the reload generation from every location it may live. Used only by the
    disarm / manual-reset path; the normal heartbeat flow NEVER clears it (see
    set_reload_flag's WHY)."""
    _flag_clear_dual("reload-needed.flag")


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
    Reads the provenance body's `set_at` (current JSON format) or the legacy
    `<epoch>\\t<reason>` tab format, across control_dir(), the pre-control-dir
    global_state_dir() location, and the legacy dir (TRDD-QK7M2B0X +
    TRDD-2U8AH82F) — an old-code session's global_control_cli may still stamp
    an older location."""
    return _generation_from_flag("skills-reload-needed.flag")


def skills_reload_flag_present() -> bool:
    return skills_reload_generation() > 0


def set_skills_reload_flag(reason: str = "") -> None:
    """Stamp the standalone-skills reload generation (current epoch) at control_dir()
    (ARCHITECTURE.md §7.1, TRDD-QK7M2B0X). Body is the provenance JSON; each session
    compares `set_at` against its per-project ack. Monotonic (wall-clock only advances)
    and NEVER cleared by a reader — clearing would starve concurrent sessions (see
    set_reload_flag's WHY)."""
    _write_flag_provenance(_skills_reload_flag_path(), reason)


def clear_skills_reload_flag() -> None:
    """Reset the standalone-skills reload generation from every location it may live.
    Used only by a manual-reset path; the normal heartbeat flow NEVER clears it."""
    _flag_clear_dual("skills-reload-needed.flag")


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
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
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


# TRDD-DB1P25S4: the DATA-staged daemon.py — the verbatim copy `launchd_keepalive.restage`
# keeps mirrored from the NEWEST cache at the FIXED persistent DATA path. Its argv carries
# no `/ai-maestro-janitor/<semver>/` cache segment BY DESIGN, so the version extractor
# below reads it as "unparseable → fail-safe restart" and a heartbeat would SIGTERM it on
# EVERY fire (the keepalive relaunches it; the next fire kills it again — the exact
# eviction loop of janitor#211 / ticket T-RVZX688P).
_DATA_STAGED_DAEMON_MARKER = (
    "/plugins/data/ai-maestro-janitor-ai-maestro-plugins/scripts/daemon.py"
)


def _is_own_stable_daemon(cmdline: str) -> bool:
    """True iff `cmdline` is a janitor daemon launched from a STABLE, version-less
    path the janitor itself owns — the L0 keepalive entry or the DATA-staged
    daemon.py. Such a daemon is by construction CURRENT (the keepalive machinery
    re-stages it from the freshest cache on every respawn), so the cache-version
    recency gate must never read its version-less argv as "stale"."""
    if "daemon_keepalive_entry.py" in cmdline:
        return True
    return _DATA_STAGED_DAEMON_MARKER in cmdline


def _restart_decision(cmdline: str, expected: str, quarantined: set[str]) -> bool:
    """PURE core of daemon_needs_restart's version-RECENCY gate (B-2 / CC 2.1.200).

    Given the running daemon's argv `cmdline`, the `expected` current-cache
    `daemon.py` path (from the version driving THIS heartbeat), and the set of
    `quarantined` version strings, decide whether to SIGTERM-and-respawn. Split
    out as a pure function so the directionality logic is unit-testable without a
    live process. The WHY of each branch:

      * keepalive / DATA-staged     → False: a daemon launched from the janitor's own
                                    FIXED version-less path (L0 entry, DATA-staged
                                    daemon.py) is re-staged from the live cache by
                                    construction. Without this guard the unparseable-
                                    version fail-safe below evicts it on EVERY fire —
                                    the self-sustaining kill loop that tripped the
                                    crash-loop breaker and falsely quarantined 2.4.1
                                    (TRDD-DB1P25S4, ticket T-RVZX688P). Guarded HERE,
                                    in the pure core, so every caller is safe — the
                                    caller-side guard alone left this hole open to any
                                    other path into this function.
      * exact path match          → False: the daemon already runs the current
                                    cache's daemon.py; nothing to roll.
      * current cache is NEWER     → roll forward ONLY iff the DECIDING (current)
                                    version is not itself QUARANTINED (janitor#211):
                                    a quarantined newer cache must never SIGTERM a
                                    healthy older daemon to reseat itself — that is
                                    the forward half of the version ping-pong (the
                                    roll-down half below correctly rolled back, the
                                    two alternated forever). When every version is
                                    quarantined the answer is "let the running daemon
                                    stand": returning False here never starves — a
                                    daemon is running by definition in this gate.
      * current cache is OLDER     → restart ONLY iff the running (newer) daemon's
                                    version is QUARANTINED and the deciding version
                                    is NOT. This is the one CC 2.1.200 fix: a mere
                                    path DIFFERENCE must not let an OLDER
                                    reinstalled/downgraded cache SIGTERM a NEWER
                                    running daemon ("older build seizes the daemon").
                                    The single legitimate downgrade is C3
                                    auto-rollback DOWN to a known-good older version
                                    after the newer one was proven bad (quarantined) —
                                    and a quarantined DECIDER is not known-good, so it
                                    may not perform even that (janitor#211 symmetry).
      * same version, other path   → False: same code, don't thrash the daemon.
      * either version unparseable → True:  fail-safe to the pre-B-2 "roll on any
                                    diff" so a genuinely-relocated/reinstalled path
                                    still rolls. A non-cache path is almost always a
                                    real reinstall, not a downgrade, so restarting is
                                    the safe default when recency can't be proven.
    """
    if _is_own_stable_daemon(cmdline):
        return False
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
        # Roll-forward — but never INTO a quarantined version (janitor#211).
        return current_ver not in quarantined
    if current_t < running_t:
        # Older heartbeat vs a newer running daemon: never downgrade UNLESS the newer
        # running version is quarantined (proven-bad → legitimate C3 rollback DOWN) AND
        # the deciding older version is itself clean (janitor#211 symmetry).
        return running_ver in quarantined and current_ver not in quarantined
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
    # the FIXED DATA path (TRDD-71ABD7V7); the DATA-staged `daemon.py` beside it is the
    # same class (TRDD-DB1P25S4). Neither argv carries a cache version, so the cache-path
    # comparison below would ALWAYS judge them "stale" and SIGTERM them — and launchd would
    # immediately respawn, so the next heartbeat SIGTERMs again: an endless restart loop.
    # They are NOT stale by that measure: the keepalive machinery re-stages the DATA copy
    # toward the freshest cache on respawn (launchd_keepalive.restage / staged_is_current).
    # Session-side restart must leave them alone. _restart_decision carries the same guard
    # in its pure core, but this early exit ALSO covers the quarantine-read-failure
    # fallback below, which bypasses _restart_decision entirely.
    if _is_own_stable_daemon(cmdline):
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
            f"daemon-restart: refusing to signal pid={pid} — cannot read its cmdline to confirm it is our daemon (a recycled pid could be any process)",
        )
        return False
    if "daemon.py" not in cmdline and "daemon_keepalive_entry.py" not in cmdline:
        # The pid is alive but is NOT the daemon → the pid was reused. Clear the stale pid
        # file so the next `ensure_daemon_running()` lazy-spawns a fresh daemon instead of
        # forever pointing at a stranger.
        state.log_line(
            "daemon",
            f"daemon-restart: pid={pid} is NOT a janitor daemon (recycled pid; cmdline={cmdline[:120]!r}) — NOT signalling it; clearing the stale daemon.pid",
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
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
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
    recent = [ln for ln in raw.splitlines() if ln.strip().isdigit() and ts - int(ln.strip()) <= _CRASH_LOOP_WINDOW_S]
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
    return sum(1 for ln in raw.splitlines() if ln.strip().isdigit() and ts - int(ln.strip()) <= win)


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
            f"wedge-kill: pid={pid} heartbeat stale but cmdline {cmdline!r} is not a janitor daemon (pid reuse?) — NOT killing; clearing nothing",
        )
        return False
    state.log_line(
        "daemon",
        f"wedge-kill: daemon pid={pid} heartbeat stale {int(time.time()) - hb}s (> {max_silence_s}s) — sending SIGTERM",
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


def _server_owns_host() -> bool:
    """True iff a live ai-maestro server owns this host (ARCHITECTURE §7.2).

    Imported LAZILY on purpose. `harness_backend` is a sibling in this same lib dir and
    today imports only `state`, but a module-level import here would make `global_state`
    — which nearly everything imports — depend on it, and any future `harness_backend`
    need for global state would become an import cycle that fails at startup rather than
    somewhere testable. The call is a single stat of a small JSON file, so the lazy
    import costs nothing on the hot path.

    FAIL-OPEN: if the probe cannot be imported or raises, we report "no server", which
    keeps the janitor daemon running. That is the safe default — the janitor covering a
    host the server also covers is wasteful and guarded by file locks, whereas a host
    with NO daemon because a probe threw is unguarded.
    """
    try:
        import harness_backend  # noqa: PLC0415  -- see docstring

        # EVERY chore claimed, not merely "a server is alive" (owner ruling 2026-08-05,
        # janitor#134). Suppressing the daemon while even one chore is unclaimed leaves
        # that chore with no runner at all: the server absorbed 5 of 11 and the daemon was
        # refused entirely, so 6 ran nowhere for 10-14 days (ai-maestro#111). The daemon
        # yields each CLAIMED chore individually, so covering the gap creates no second
        # owner for anything the server actually runs.
        return harness_backend.server_owns_every_chore()
    except Exception:
        return False


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
    if state.in_ai_maestro_agent_env():
        # #J THIN MODE (TRDD-PZLVT2RN): a harness agent must never spawn (or adopt)
        # the machine-global daemon — for harness agents the ai-maestro SERVER *is*
        # the daemon, and the standalone daemon belongs to the OUTSIDE world's
        # sessions. Gated HERE, at the single spawn choke point, so all four callers
        # (dispatch's two phases + the marketplace/user-plugins shims) are covered
        # at once. Same discriminator harness_backend.is_harness_session wraps.
        return False
    if kill_switch_present():
        return False
    if _server_owns_host():
        # ONE DAEMON PER HOST (TRDD-5ZVS1DDP, ARCHITECTURE §7.2). A live ai-maestro
        # server owns this host, so no session may spawn the standalone daemon —
        # otherwise the daemon that just exited for exactly this reason would be
        # resurrected by the very next heartbeat fire, and the two-owner condition
        # (concurrent writers on one state dir, chores run twice) would reappear
        # within seconds. Gated at the SAME choke point as the #J thin-mode guard
        # above so every caller is covered once.
        #
        # Returning BEFORE the crash-loop breaker is deliberate: this is a normal,
        # expected refusal, not evidence the daemon is failing to start. Counting it
        # would trip the breaker during a server's lifetime and then suppress the
        # legitimate spawn after the server stops.
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
            f"spawn refused — crash-loop breaker tripped ({_CRASH_LOOP_SPAWN_LIMIT}+ attempts in {_CRASH_LOOP_WINDOW_S}s); will retry once attempts age out",
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
