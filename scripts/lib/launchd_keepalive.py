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

import filecmp
import os
import shutil
import subprocess
import sys
from pathlib import Path

import keepalive_stage  # sibling in scripts/lib/; computes + verbatim-stages the closure

# The janitor's FIXED persistent DATA dir — hard-coded (NOT ${CLAUDE_PLUGIN_DATA}, which
# resolves to whichever plugin owns the current turn, wrong in a detached/session-less
# daemon). The same hard-coded location the arm skill + the memory subsystem use.
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
    return _DATA_DIR


def data_scripts_dir() -> Path:
    """Where the verbatim daemon closure + the installer are staged (beside the entry the
    OS service launches at the fixed DATA path)."""
    return _DATA_DIR / "scripts"


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
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE", "1").strip().lower()
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
    os.chmod(tmp, 0o755)
    os.replace(tmp, dest)
    return dest


def _version_key(name: str) -> tuple[int, ...]:
    """Sort key for a semver-ish cache dir name (``0.18.0`` → ``(0, 18, 0)``). A
    non-numeric name sorts lowest so it never wins over a real version."""
    try:
        return tuple(int(p) for p in name.split("."))
    except ValueError:
        return (-1,)


def latest_cache_scripts_dir() -> Path | None:
    """The ``scripts/`` dir of the NEWEST cached plugin version (from the fixed cache
    location), or ``None`` when no usable cache is present (e.g. an inline/dev install).
    Only versions that actually carry the entry + daemon are considered. The OS-spawned
    daemon — which runs from DATA and cannot see the cache via its own ``__file__`` — uses
    this to re-stage the freshest closure into DATA, so it self-heals toward the current
    version. Dirs are read only to COPY from, never to exec."""
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
    return candidates[-1] / "scripts"


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
    """True iff the staged DATA ``daemon.py`` is byte-identical to ``source_scripts_dir``'s
    ``daemon.py``. When False, a newer/different version is available and the OS-spawned
    daemon should ``restage`` + exit so launchd respawns it on the fresh code. False if
    either file is missing (the caller only acts when a real source dir was resolved)."""
    staged = data_scripts_dir() / "daemon.py"
    src = source_scripts_dir / "daemon.py"
    if not staged.is_file() or not src.is_file():
        return False
    return filecmp.cmp(staged, src, shallow=False)


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
    """True iff the OS-keepalive artifact for this platform is on disk, as reported by the
    staged installer's ``status`` subcommand — so this module names no service path of its
    own (the path knowledge lives only in the scanned installer)."""
    installer = data_scripts_dir() / _INSTALLER_NAME
    if not installer.is_file():
        return False
    ok, _ = _run(["bash", str(installer), "status"])
    return ok
