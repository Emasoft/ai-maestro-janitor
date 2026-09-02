"""OS keepalive orchestrator for the global daemon (TRDD-71ABD7V7, GROUP B / L0).

The L1 daemon recovers frozen sessions — but what restarts the DAEMON if it dies? Today
only a session heartbeat (``ensure_daemon_running``), which is circular: if every session
is frozen, none fires to respawn the daemon, and a dead daemon can't recover the very
sessions whose heartbeats would restart it. This module closes that gap at the OS level
(L0): it stages the daemon's verbatim import closure into the FIXED persistent DATA dir
and asks the shipped shell installer (``keepalive_install.sh``) to register an OS service
that respawns the daemon regardless of any Claude session — across crash, logout, reboot.

SPLIT OF RESPONSIBILITY (the design keystone — see ``keepalive_install.sh``'s header): the
OS-service registration — the install verbs AND the service-config body that CPV's #152
discriminator must resolve — lives ENTIRELY in the scanned shell installer. This Python
file performs NO OS-service install and constructs NO service-config path; it only stages
files and runs ``bash keepalive_install.sh <cmd>``. That separation is what keeps this
module off CPV's persistence radar: the earlier version of this file wrote the OS-service
config itself, which the discriminator could not resolve, and it was extracted in v0.16.0
for exactly that reason. The clean inert entry the service launches is resolved + scanned
by the discriminator from the installer's heredoc, never from here.

Everything here is best-effort and never raises into the daemon: a keepalive that cannot
install must not kill the very daemon it was meant to protect.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import keepalive_stage  # sibling in scripts/lib/; computes + verbatim-stages the closure
import state  # sibling in scripts/lib/; plugin_option() reads the settings.json mirror
import version_update_lib  # sibling in scripts/lib/; the C3 quarantine reader (read_quarantine)

# The janitor's FIXED persistent DATA dir — hard-coded (NOT ${CLAUDE_PLUGIN_DATA}, which
# resolves to whichever plugin owns the current turn, wrong in a detached/session-less
# daemon). The same hard-coded location the arm skill + the memory subsystem use. This is
# the FALLBACK value; data_dir() re-resolves it at CALL time and honors JANITOR_DATA_DIR —
# the same test-only override version_update_lib._data_dir() uses — so no test touches the
# real ~/.claude tree (TRDD-ZNN0UK5K).
_DATA_DIR = Path.home() / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"
_INSTALLER_NAME = "keepalive_install.sh"
# The FIXED plugin-cache location (the marketplace install path). The OS-spawned daemon
# runs from DATA and cannot see the cache via its own __file__, so it resolves the freshest
# version from this hard-coded path to re-stage from — reading the dirs only to COPY, never
# to exec (so it is not the dynamic-loading anti-pattern the design forbids).
_CACHE_PARENT = (
    Path.home() / ".claude" / "plugins" / "cache" / "ai-maestro-plugins" / "ai-maestro-janitor"
)


def data_dir() -> Path:
    """The janitor's FIXED persistent DATA dir, resolved AT CALL TIME.

    Honors ``JANITOR_DATA_DIR`` when set — the SAME test-only override
    ``version_update_lib._data_dir()`` reads (the janitor's canonical DATA-dir isolation
    lever). A frozen module constant (``_DATA_DIR``, computed from ``Path.home()`` at
    import) made the keepalive TESTS resolve to the REAL DATA dir and restage the real
    closure, driving a 39 GB fseventsd runaway (TRDD-ZNN0UK5K); reading the override here at
    call time is the sibling fix to ``keepalive_boot._state_dir()``. It deliberately does
    NOT read ``${CLAUDE_PLUGIN_DATA}`` — per this module's design that env points at
    whichever plugin owns the current turn, wrong both in the detached daemon and in a
    session where another plugin owns the turn (e.g. ``fleet_status``'s keepalive probe). In
    production the override is unset, so this falls back to the hard-coded FIXED path
    (identical behavior to before)."""
    override = os.environ.get("JANITOR_DATA_DIR", "").strip()
    if override:
        return Path(override)
    return _DATA_DIR


def data_scripts_dir() -> Path:
    """Where the verbatim daemon closure + the installer are staged (beside the entry the
    OS service launches at the fixed DATA path). Resolved via ``data_dir()`` so the
    ``JANITOR_DATA_DIR`` test override reaches it too (TRDD-ZNN0UK5K)."""
    return data_dir() / "scripts"


def current_platform() -> str:
    """'macos' | 'linux' | 'other' — whether an OS keepalive is available here."""
    plat = str(sys.platform)  # str() defeats pyright's single-platform Literal narrowing
    if plat == "darwin":
        return "macos"
    if plat.startswith("linux"):
        return "linux"
    return "other"


def opted_in() -> bool:
    """Master opt-in for the OS keepalive. Default ON (the user mandated OS-level
    immortality). Set ``CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE=0`` to keep the daemon
    session-spawned only. It is removed when the daemon stops machine-wide (the
    kill-switch exit calls ``uninstall``), NOT by a per-project /janitor-disarm — the
    daemon is a machine-global singleton other projects rely on."""
    raw = (state.plugin_option("CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE", "1") or "").strip().lower()
    return raw not in ("0", "false", "no", "off", "")


def _run(cmd: list[str]) -> tuple[bool, str]:
    """Best-effort fixed-argv subprocess (no shell). Returns (ok, combined-output);
    never raises — any OS/subprocess error becomes (False, message)."""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, 30s cap
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            text=True,
        )
        return proc.returncode == 0, (proc.stdout or "").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def _stage_installer(source_scripts_dir: Path) -> Path:
    """Verbatim-copy the shell installer into the staged DATA scripts dir (atomic: tmp +
    ``os.replace``), so the OS-spawned daemon — which runs from DATA, not the ephemeral
    plugin cache — can later uninstall itself from there. Returns the staged path."""
    src = source_scripts_dir / _INSTALLER_NAME
    dest = data_scripts_dir() / _INSTALLER_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.tmp.{os.getpid()}")
    shutil.copyfile(src, tmp)  # byte-identical copy of the CPV-scanned installer
    os.chmod(tmp, 0o755)  # nosec B103 -- staged installer must be executable (launchd/systemd exec via shebang); 0o755 intended
    os.replace(tmp, dest)
    return dest


def _version_key(name: str) -> tuple[int, ...]:
    """Sort key for a semver-ish cache dir name (``0.18.0`` → ``(0, 18, 0)``). A
    non-numeric name sorts lowest so it never wins over a real version."""
    try:
        return tuple(int(p) for p in name.split("."))
    except ValueError:
        return (-1,)


def _read_quarantine() -> set[str]:
    """The C3 quarantine set (proven-bad version strings), FAIL-OPEN: any fault →
    EMPTY set. C4 auto-rollback covers the heartbeat via the dispatcher-stub's C3
    skip, but the OS-respawn path is otherwise quarantine-blind — so the keepalive's
    version selection MUST consult the same set, or launchd resurrects a quarantined
    daemon forever (KEEPQRTN HIGH-1/MEDIUM-1). The read is wrapped so a raising /
    unreadable / corrupt quarantine NEVER makes us select a WORSE version than today:
    an empty set means "skip nothing", exactly as if no quarantine existed — and
    `version_update_lib.read_quarantine` is itself fail-open, this `except` is the
    second belt against any unexpected import/attr error."""
    try:
        return version_update_lib.read_quarantine()
    except Exception:  # noqa: BLE001 — fail-open: a quarantine fault must never starve the daemon
        return set()


def latest_cache_scripts_dir() -> Path | None:
    """The ``scripts/`` dir of the newest cached plugin version that is NOT C3-quarantined
    (from the fixed cache location), or ``None`` when no usable cache is present (e.g. an
    inline/dev install). Only versions that actually carry the entry + daemon are
    considered. The OS-spawned daemon — which runs from DATA and cannot see the cache via
    its own ``__file__`` — uses this to re-stage the freshest closure into DATA, so it
    self-heals toward the current GOOD version. Dirs are read only to COPY from, never to
    exec.

    QUARANTINE-AWARE (KEEPQRTN, mirrors the dispatcher-stub's C3 walk at
    ``dispatcher-stub.py:232-263`` exactly — same policy, not a new one): walk versions
    newest→oldest and SKIP any that the C3 quarantine marks proven-bad, returning the
    newest NON-quarantined version. FAIL-OPEN cardinal rule (the stub's): the newest
    runnable version is captured BEFORE the quarantine skip as the backstop, so if EVERY
    cached version is quarantined we still select the newest (a running daemon beats none),
    and a raising/unreadable quarantine reads as EMPTY (select newest, never worse than
    today). We never return ``None`` because of quarantine — only because the cache itself
    is absent or carries no complete version."""
    if not _CACHE_PARENT.is_dir():
        return None
    candidates = [
        d
        for d in _CACHE_PARENT.iterdir()
        if d.is_dir()
        and (d / "scripts" / "daemon.py").is_file()
        and (d / "scripts" / "daemon_keepalive_entry.py").is_file()
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda d: _version_key(d.name))
    # newest runnable = the fail-open backstop, captured BEFORE the quarantine skip (the
    # stub's invariant: when all else is rejected, the daemon must still have code to run).
    newest_runnable = candidates[-1] / "scripts"
    quarantined = _read_quarantine()
    for version_dir in reversed(candidates):  # newest first, like the stub
        if version_dir.name in quarantined:
            continue
        return version_dir / "scripts"
    # Every cached version is quarantined → select the newest anyway (a running daemon
    # beats none — the stub's cardinal rule); never starve the OS keepalive on quarantine.
    return newest_runnable


def restage(source_scripts_dir: Path) -> None:
    """Verbatim-refresh the DATA closure + installer from ``source_scripts_dir`` WITHOUT
    touching the OS service manager (no activation, no bootout). Safe to call on every
    daemon startup: it keeps the FIXED-path DATA copy current so the next OS respawn runs
    the freshest scanned code. Raises OSError on an I/O failure (callers wrap best-effort)."""
    keepalive_stage.stage_closure(source_scripts_dir, data_scripts_dir())
    _stage_installer(source_scripts_dir)


def activate() -> tuple[bool, str]:
    """Run the STAGED installer's ``install`` to register the OS service (idempotent).
    Kept SEPARATE from ``restage`` so the daemon can refresh DATA on every startup but
    register the OS service only ONCE — re-running the registration on a launchd-spawned
    daemon's own startup would bootout the running process (a self-kill loop)."""
    installer = data_scripts_dir() / _INSTALLER_NAME
    if not installer.is_file():
        return False, "no staged installer to activate"
    return _run(["bash", str(installer), "install"])


def staged_is_current(source_scripts_dir: Path) -> bool:
    """True iff EVERY file of the daemon's staged import closure is byte-identical to
    ``source_scripts_dir``'s copy. When False, a newer/different/incomplete stage exists and
    the OS-spawned daemon should ``restage`` + exit so launchd respawns on the fresh code.
    False if the source dir carries no ``daemon.py`` (nothing to compare), the closure can't
    be computed, or any closure file is missing/unreadable/mismatched.

    Two bugs this shape fixes (TRDD-K3WQ7XM9 bug #2), both proven to report a STALE stage as
    "current" — starving the OS-respawn self-heal so the launchd daemon kept booting old code:

    * WRONG FILE SET — the old check compared ONLY ``daemon.py``. A stale ``lib/`` closure
      file (e.g. an old ``global_state.py``) with a current ``daemon.py`` read as "current",
      so the OS daemon ran fresh ``daemon.py`` against stale libs. We now compare the WHOLE
      closure (``keepalive_stage.daemon_closure`` — the exact set ``restage`` copies).
    * FILECMP CACHE FALSE-POSITIVE — ``filecmp.cmp(shallow=False)`` keeps a MODULE-LEVEL
      cache keyed on ``(path, path, sig, sig)`` where ``sig`` is ``(mode, size, mtime)``.
      After a file is overwritten with same-size/same-mtime BUT DIFFERENT content, the cache
      returns its stale ``True`` (empirically confirmed). We read bytes directly instead —
      no cross-call cache — so a changed-but-same-signature file is always detected."""
    if not (source_scripts_dir / "daemon.py").is_file():
        return False
    dest_scripts = data_scripts_dir()
    try:
        closure = keepalive_stage.daemon_closure(source_scripts_dir)
    except (OSError, SyntaxError, ValueError):
        # An unreadable / unparseable source daemon.py can't be proven current → restage.
        return False
    if not closure:
        return False
    for src in closure:
        staged = dest_scripts / src.relative_to(source_scripts_dir)
        try:
            if not staged.is_file() or staged.read_bytes() != src.read_bytes():
                return False
        except OSError:
            return False
    return True


def install(source_scripts_dir: Path) -> tuple[bool, str]:
    """Stage the daemon closure + installer into DATA, then register the OS service —
    ``restage`` + ``activate`` in one. Idempotent + best-effort; never raises.
    ``source_scripts_dir`` is the shipped ``scripts/`` dir (cache or repo) holding
    ``daemon_keepalive_entry.py``, ``daemon.py`` + its closure, and ``keepalive_install.sh``."""
    if current_platform() == "other":
        return False, f"no OS keepalive for platform {sys.platform}"
    try:
        restage(source_scripts_dir)
    except OSError as exc:
        return False, f"could not stage keepalive: {exc}"
    return activate()


def uninstall() -> tuple[bool, str]:
    """Run the STAGED installer's uninstall (idempotent, best-effort, never raises). Uses
    the staged copy so the OS-spawned daemon (running from DATA, with no access to the
    plugin cache) can remove its own OS service on a kill-switch exit. A missing staged
    installer means nothing was ever installed → success no-op."""
    installer = data_scripts_dir() / _INSTALLER_NAME
    if not installer.is_file():
        return True, "no staged keepalive installer; nothing to remove"
    return _run(["bash", str(installer), "uninstall"])


def is_installed() -> bool:
    """True iff the OS-keepalive job for this platform is actually LOADED/ACTIVE with the
    service manager (not merely that its definition FILE exists on disk — janitor#217: an
    operator-driven unload can leave the definition file in place while unloading the job),
    as reported by the staged installer's ``status`` subcommand — so this module names no
    service path or persistence verb of its own (that knowledge lives only in the scanned
    installer)."""
    installer = data_scripts_dir() / _INSTALLER_NAME
    if not installer.is_file():
        return False
    ok, _ = _run(["bash", str(installer), "status"])
    return ok
