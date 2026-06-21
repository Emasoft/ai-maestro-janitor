"""OS keepalive for the global daemon (TRDD-324223a6, GROUP B / B1+B2).

The L1 daemon recovers frozen sessions — but what restarts the DAEMON if it dies?
Today only a session heartbeat (``ensure_daemon_running``), which is circular: if
every session is frozen, none fires to respawn the daemon, and a dead daemon can't
recover the sessions whose heartbeats would restart it. This module closes that
gap at the OS level (L0): a macOS LaunchAgent (``KeepAlive`` + ``RunAtLoad``) or a
Linux systemd user unit (``Restart=always``) respawns the daemon regardless of any
Claude session — even across crash, logout, and reboot. That is the anchor's anchor.

The OS service runs the STABLE ``daemon-launcher.py`` stub in the persistent DATA
dir (not a version-stamped cache path), so it survives plugin updates and the
launcher self-rolls to the newest ``daemon.py``. The daemon's singleton flock makes
the OS-spawned daemon coexist safely with the session-spawn path — only one runs.

Everything that builds a string (the plist / unit text, the paths, the platform +
opt-in decisions) is PURE and tested; the install/uninstall do best-effort I/O and
never raise into the daemon (a keepalive that can't install must not kill the very
daemon it was meant to protect).
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

LABEL = "com.ai-maestro-janitor.daemon"

# The janitor's FIXED persistent DATA dir — the same hard-coded location the arm
# skill and the memory subsystem use (NOT ${CLAUDE_PLUGIN_DATA}, which resolves to
# the RUNNING plugin's dir and would be wrong in a detached daemon's environment).
_DATA_DIR = Path.home() / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"


def data_dir() -> Path:
    return _DATA_DIR


def launcher_dest() -> Path:
    """Where the stable launcher stub lives (the OS service's ProgramArguments[1])."""
    return _DATA_DIR / "daemon-launcher.py"


def current_platform() -> str:
    """'macos' | 'linux' | 'other' — selects launchd vs systemd vs no-op."""
    plat = str(sys.platform)  # str() defeats pyright's single-platform Literal narrowing
    if plat == "darwin":
        return "macos"
    if plat.startswith("linux"):
        return "linux"
    return "other"


def opted_in() -> bool:
    """Master opt-in for the OS keepalive. Default ON — the user mandated launchd
    immortality. It is removed when the daemon STOPS machine-wide — the kill-switch
    flag (the daemon uninstalls it on that exit) or a full plugin uninstall (the
    launcher self-uninstalls when its cache is gone) — NOT by per-project
    /janitor-disarm, since the daemon is a machine-global singleton other projects
    rely on. Set CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE=0 to keep the daemon
    session-spawned only (no OS keepalive at all)."""
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE", "1").strip().lower()
    return raw not in ("0", "false", "no", "off", "")


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def systemd_unit_path() -> Path:
    cfg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(cfg) / "systemd" / "user" / f"{LABEL}.service"


def plist_bytes(python: str, launcher: str, log_dir: str) -> bytes:
    """The LaunchAgent plist. KeepAlive=true → launchd respawns the daemon on ANY
    exit (crash OR a plugin-version-roll SIGTERM); RunAtLoad → start at login;
    ThrottleInterval caps the respawn rate so a crash-loop can't hammer. The daemon
    logs to JANITOR_LOG_DIR; the plist's stdout/stderr capture only the launcher's
    own resolution errors. (The daemon uninstalls this agent on a kill-switch exit,
    so KeepAlive never fights a deliberate machine-wide stop.)"""
    spec = {
        "Label": LABEL,
        "ProgramArguments": [python, launcher],
        "KeepAlive": True,
        "RunAtLoad": True,
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "EnvironmentVariables": {"JANITOR_LOG_DIR": log_dir},
        "StandardOutPath": str(Path(log_dir) / "daemon-launcher.out.log"),
        "StandardErrorPath": str(Path(log_dir) / "daemon-launcher.err.log"),
    }
    return plistlib.dumps(spec)


def systemd_unit(python: str, launcher: str, log_dir: str) -> str:
    """A systemd USER unit (Linux). Restart=always is the launchd-KeepAlive analog;
    RestartSec mirrors ThrottleInterval. WantedBy=default.target starts it at login."""
    return (
        "[Unit]\n"
        "Description=ai-maestro-janitor global daemon (OS keepalive)\n"
        "After=default.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={python} {launcher}\n"
        "Restart=always\n"
        "RestartSec=30\n"
        f"Environment=JANITOR_LOG_DIR={log_dir}\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _stage_launcher(source_launcher: Path) -> Path:
    """Copy the launcher stub into the persistent DATA dir (atomic). Returns dest."""
    dest = launcher_dest()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.tmp.{os.getpid()}")
    shutil.copyfile(source_launcher, tmp)
    os.chmod(tmp, 0o755)
    os.replace(tmp, dest)
    return dest


def _run(cmd: list[str]) -> bool:
    """Best-effort subprocess; True iff it exited 0. Never raises."""
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=30,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def is_installed() -> bool:
    """True iff the OS keepalive artifact for this platform is present on disk."""
    plat = current_platform()
    if plat == "macos":
        return plist_path().exists()
    if plat == "linux":
        return systemd_unit_path().exists()
    return False


def install(source_launcher: Path, log_dir: Path) -> tuple[bool, str]:
    """Install + start the OS keepalive (idempotent). Best-effort: returns
    (ok, message); never raises. Stages the launcher into DATA, writes the
    plist/unit, and (re)loads it via launchctl/systemctl."""
    plat = current_platform()
    if plat == "other":
        return False, f"no OS keepalive for platform {sys.platform}"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        launcher = _stage_launcher(source_launcher)
    except OSError as exc:
        return False, f"could not stage launcher: {exc}"
    python = sys.executable
    if plat == "macos":
        try:
            p = plist_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(plist_bytes(python, str(launcher), str(log_dir)))
        except OSError as exc:
            return False, f"could not write plist: {exc}"
        uid = os.getuid()
        _run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"])  # clear any stale instance
        ok = _run(["launchctl", "bootstrap", f"gui/{uid}", str(p)])
        if not ok:  # older macOS / fallback path
            ok = _run(["launchctl", "load", "-w", str(p)])
        return (ok, "launchd keepalive installed" if ok
                else "plist written but launchctl load failed")
    # linux
    try:
        u = systemd_unit_path()
        u.parent.mkdir(parents=True, exist_ok=True)
        u.write_text(systemd_unit(python, str(launcher), str(log_dir)), encoding="utf-8")
    except OSError as exc:
        return False, f"could not write systemd unit: {exc}"
    _run(["systemctl", "--user", "daemon-reload"])
    ok = _run(["systemctl", "--user", "enable", "--now", f"{LABEL}.service"])
    return ok, "systemd keepalive installed" if ok else "unit written but systemctl enable failed"


def uninstall() -> tuple[bool, str]:
    """Stop + remove the OS keepalive (idempotent). Best-effort; never raises. Called
    on the daemon's kill-switch exit (and self-invoked by the launcher when the plugin
    cache is gone) so KeepAlive never resurrects a daemon the user deliberately
    stopped, nor churns after the plugin is uninstalled."""
    plat = current_platform()
    if plat == "macos":
        uid = os.getuid()
        _run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"])
        _run(["launchctl", "unload", "-w", str(plist_path())])  # legacy fallback
        try:
            plist_path().unlink(missing_ok=True)
        except OSError as exc:
            return False, f"booted out but could not remove plist: {exc}"
        return True, "launchd keepalive removed"
    if plat == "linux":
        _run(["systemctl", "--user", "disable", "--now", f"{LABEL}.service"])
        try:
            systemd_unit_path().unlink(missing_ok=True)
        except OSError as exc:
            return False, f"disabled but could not remove unit: {exc}"
        _run(["systemctl", "--user", "daemon-reload"])
        return True, "systemd keepalive removed"
    return True, "no OS keepalive to remove"
