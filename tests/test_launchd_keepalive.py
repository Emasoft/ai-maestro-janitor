"""Tests for the OS keepalive (TRDD-324223a6, GROUP B).

The plist/unit text, the paths, and the platform + opt-in decisions are pure and
checked directly. install()/uninstall() are exercised with the launchctl/systemctl
call stubbed and the artifact paths redirected to a tmp dir, so a test NEVER
registers a real LaunchAgent on the developer's machine — it proves the file
staging + plist content + load-command wiring without any system side effect.
"""

from __future__ import annotations

import importlib.util
import plistlib
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import launchd_keepalive as lk  # type: ignore[import-not-found]  # noqa: E402


def test_plist_is_valid_and_keepalive() -> None:
    """The plist parses, is KeepAlive + RunAtLoad, runs python+launcher, throttles,
    and pins JANITOR_LOG_DIR so the daemon logs deterministically under launchd."""
    data = plistlib.loads(lk.plist_bytes("/usr/bin/python3", "/data/daemon-launcher.py", "/logs"))
    assert data["Label"] == lk.LABEL
    assert data["KeepAlive"] is True
    assert data["RunAtLoad"] is True
    assert data["ProgramArguments"] == ["/usr/bin/python3", "/data/daemon-launcher.py"]
    assert data["ThrottleInterval"] >= 10            # launchd's minimum respawn floor
    assert data["EnvironmentVariables"]["JANITOR_LOG_DIR"] == "/logs"
    assert data["StandardErrorPath"].endswith(".err.log")


def test_systemd_unit_restarts_always() -> None:
    """The Linux unit is the launchd analog: Restart=always + a respawn delay +
    WantedBy=default.target (start at login)."""
    unit = lk.systemd_unit("/usr/bin/python3", "/data/daemon-launcher.py", "/logs")
    assert "Restart=always" in unit
    assert "ExecStart=/usr/bin/python3 /data/daemon-launcher.py" in unit
    assert "RestartSec=30" in unit
    assert "WantedBy=default.target" in unit
    assert "Environment=JANITOR_LOG_DIR=/logs" in unit


def test_opted_in_default_on_and_overrides(monkeypatch) -> None:
    """Default ON (the user mandated launchd); the documented false spellings turn
    it off so the daemon stays session-spawned only."""
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE", raising=False)
    assert lk.opted_in() is True
    for off in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE", off)
        assert lk.opted_in() is False
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE", "1")
    assert lk.opted_in() is True


def test_current_platform_maps_sys_platform(monkeypatch) -> None:
    """darwin→macos, linux*→linux, anything else→other (a no-op platform)."""
    monkeypatch.setattr(lk.sys, "platform", "darwin")
    assert lk.current_platform() == "macos"
    monkeypatch.setattr(lk.sys, "platform", "linux")
    assert lk.current_platform() == "linux"
    monkeypatch.setattr(lk.sys, "platform", "win32")
    assert lk.current_platform() == "other"


def test_install_macos_stages_launcher_writes_plist_and_loads(tmp_path, monkeypatch) -> None:
    """macОС install: the launcher is copied into DATA, a valid plist is written, and
    a launchctl load is attempted — all without touching the real LaunchAgents dir."""
    monkeypatch.setattr(lk.sys, "platform", "darwin")
    monkeypatch.setattr(lk, "launcher_dest", lambda: tmp_path / "daemon-launcher.py")
    monkeypatch.setattr(lk, "plist_path", lambda: tmp_path / "agent.plist")
    cmds: list = []
    monkeypatch.setattr(lk, "_run", lambda cmd: bool(cmds.append(cmd)) or True)
    src = tmp_path / "src-launcher.py"
    src.write_text("# launcher", encoding="utf-8")
    ok, msg = lk.install(src, tmp_path / "logs")
    assert ok, msg
    assert (tmp_path / "daemon-launcher.py").read_text(encoding="utf-8") == "# launcher"
    plist = plistlib.loads((tmp_path / "agent.plist").read_bytes())
    assert plist["Label"] == lk.LABEL and plist["KeepAlive"] is True
    assert any("bootstrap" in " ".join(c) or "load" in " ".join(c) for c in cmds)


def test_uninstall_macos_boots_out_and_removes(tmp_path, monkeypatch) -> None:
    """macOS uninstall boots the job out and removes the plist (idempotent: a missing
    plist is fine)."""
    monkeypatch.setattr(lk.sys, "platform", "darwin")
    p = tmp_path / "agent.plist"
    p.write_text("x", encoding="utf-8")
    monkeypatch.setattr(lk, "plist_path", lambda: p)
    cmds: list = []
    monkeypatch.setattr(lk, "_run", lambda cmd: bool(cmds.append(cmd)) or True)
    ok, msg = lk.uninstall()
    assert ok, msg
    assert not p.exists()
    assert any("bootout" in " ".join(c) for c in cmds)


def test_daemon_launcher_version_key_orders_semver() -> None:
    """The launcher's version sort matches the stub contract: highest semver wins,
    non-numeric dirs sort lowest (so a stray dir never out-ranks a real version)."""
    spec = importlib.util.spec_from_file_location(
        "daemon_launcher", _PROJECT_ROOT / "scripts" / "daemon-launcher.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    keys = sorted([Path("0.9.0"), Path("0.15.0"), Path("0.2.0"), Path("nightly")], key=mod._version_key)
    assert [k.name for k in keys] == ["nightly", "0.2.0", "0.9.0", "0.15.0"]


def test_daemon_stays_dependency_free_for_the_python3_launcher_path() -> None:
    """The OS keepalive runs daemon.py under PLAIN python3 (a stable LaunchAgent
    program path), bypassing `uv run --script`. That is safe ONLY while daemon.py
    imports nothing outside stdlib + local modules. Guard it: daemon.py's PEP-723
    block must declare NO third-party dependencies — so a future dep addition fails
    HERE (loudly, in CI) instead of crash-looping the LaunchAgent at runtime with a
    ModuleNotFoundError that KeepAlive=true would hammer every 30s forever."""
    text = (_PROJECT_ROOT / "scripts" / "daemon.py").read_text(encoding="utf-8")
    block = re.search(r"^# /// script\s*$(.*?)^# ///\s*$", text, re.MULTILINE | re.DOTALL)
    assert block, "daemon.py must carry a PEP-723 `# /// script` block"
    dep = re.search(r"^#\s*dependencies\s*=\s*\[(.*?)\]", block.group(1), re.MULTILINE | re.DOTALL)
    deps_inner = (dep.group(1) if dep else "").strip()
    assert deps_inner == "", (
        "daemon.py must stay dependency-free for the keepalive's python3 launch path; "
        f"found PEP-723 dependencies: {deps_inner!r}. Either drop the dep or teach "
        "daemon-launcher.py to exec via `uv run --script` when uv is present."
    )
