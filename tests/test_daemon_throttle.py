"""Tests for scripts/lib/daemon_throttle.py — the low-priority throttle for the
daemon's marketplace-refresh subprocess (TRDD-TY2EZ8ZH, task #244).

The PURE function `low_priority_prefix` takes a platform string + three
tool-availability booleans, so it is exercised DIRECTLY with no mocking. The thin
detector `_low_priority_prefix()` is tested by monkeypatching only its detection
seam (`sys.platform` + `shutil.which`). `nice_preexec()` is checked for the POSIX
callable + the Windows None + the fail-open swallow.

The wiring test asserts that the throttle prefix flows into the marketplace argv
when launchers are present and degrades cleanly to the bare command when absent —
the FAIL-OPEN contract the daemon depends on.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LIB = _PROJECT_ROOT / "scripts" / "lib"
_MODULE_PATH = _LIB / "daemon_throttle.py"

assert _MODULE_PATH.is_file(), f"module not found at {_MODULE_PATH}"


def _load_daemon_throttle():
    """Import scripts/lib/daemon_throttle.py as a standalone module.

    Loaded by file path (the daemon imports it via a sys.path insert of
    scripts/lib), so the test does not depend on package layout.
    """
    spec = importlib.util.spec_from_file_location("daemon_throttle", _MODULE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dt = _load_daemon_throttle()


# --- low_priority_prefix: PURE, no mocking --------------------------------

@pytest.mark.parametrize(
    "platform, has_taskpolicy, has_nice, has_ionice, expected",
    [
        # macOS: taskpolicy -b (background QoS) when present; else fail-open [].
        ("darwin", True, True, True, ["taskpolicy", "-b"]),
        ("darwin", True, False, False, ["taskpolicy", "-b"]),
        ("darwin", False, True, True, []),  # nice/ionice are NOT used on macOS
        ("darwin", False, False, False, []),
        # Linux: nice -n 19 + ionice -c 3, each gated on availability.
        ("linux", True, True, True, ["nice", "-n", "19", "ionice", "-c", "3"]),
        ("linux2", True, True, True, ["nice", "-n", "19", "ionice", "-c", "3"]),
        ("linux", True, True, False, ["nice", "-n", "19"]),
        ("linux", True, False, True, ["ionice", "-c", "3"]),
        ("linux", True, False, False, []),  # nothing available → fail-open
        # taskpolicy presence is irrelevant on Linux.
        ("linux", False, True, True, ["nice", "-n", "19", "ionice", "-c", "3"]),
        # Unknown / unsupported platforms → fail-open [] regardless of tools.
        ("win32", True, True, True, []),
        ("cygwin", True, True, True, []),
        ("freebsd13", False, True, True, []),
        ("", True, True, True, []),
    ],
)
def test_low_priority_prefix_matrix(platform, has_taskpolicy, has_nice, has_ionice, expected):
    """low_priority_prefix returns the exact launcher prefix per platform x tools."""
    got = dt.low_priority_prefix(
        platform,
        has_taskpolicy=has_taskpolicy,
        has_nice=has_nice,
        has_ionice=has_ionice,
    )
    assert got == expected


def test_low_priority_prefix_nice_outermost_on_linux():
    """On Linux nice precedes ionice so the renice wraps the idle-IO launcher."""
    got = dt.low_priority_prefix("linux", has_taskpolicy=False, has_nice=True, has_ionice=True)
    assert got.index("nice") < got.index("ionice")


# --- _low_priority_prefix: the detection seam -----------------------------

def test_detector_uses_taskpolicy_on_macos(monkeypatch):
    """_low_priority_prefix picks taskpolicy -b on a darwin host that has it."""
    monkeypatch.setattr(dt.sys, "platform", "darwin")
    monkeypatch.setattr(dt.shutil, "which", lambda name: "/usr/bin/taskpolicy" if name == "taskpolicy" else None)
    assert dt._low_priority_prefix() == ["taskpolicy", "-b"]


def test_detector_builds_linux_prefix(monkeypatch):
    """_low_priority_prefix builds nice + ionice when both are on a linux host."""
    monkeypatch.setattr(dt.sys, "platform", "linux")
    present = {"nice", "ionice"}
    monkeypatch.setattr(dt.shutil, "which", lambda name: f"/usr/bin/{name}" if name in present else None)
    assert dt._low_priority_prefix() == ["nice", "-n", "19", "ionice", "-c", "3"]


def test_detector_fails_open_when_no_tools(monkeypatch):
    """_low_priority_prefix returns [] (un-throttled) when no launcher is present."""
    monkeypatch.setattr(dt.sys, "platform", "darwin")
    monkeypatch.setattr(dt.shutil, "which", lambda name: None)
    assert dt._low_priority_prefix() == []


def test_detector_fails_open_on_exception(monkeypatch):
    """A probe error degrades to [] rather than crashing the daemon."""
    monkeypatch.setattr(dt.sys, "platform", "linux")

    def _boom(_name):
        raise RuntimeError("which exploded")

    monkeypatch.setattr(dt.shutil, "which", _boom)
    assert dt._low_priority_prefix() == []


# --- nice_preexec ----------------------------------------------------------

@pytest.mark.skipif(not hasattr(__import__("os"), "nice"), reason="os.nice is POSIX-only")
def test_nice_preexec_returns_callable_that_does_not_raise():
    """On POSIX, nice_preexec returns a callable that renices without raising."""
    fn = dt.nice_preexec()
    assert callable(fn)
    fn()  # must not raise even though the test process renices itself


def test_nice_preexec_none_without_os_nice(monkeypatch):
    """Where os.nice is unavailable (e.g. Windows) nice_preexec returns None."""
    monkeypatch.delattr(dt.os, "nice", raising=False)
    assert dt.nice_preexec() is None


def test_nice_preexec_swallows_renice_error(monkeypatch):
    """The returned preexec swallows an os.nice failure (fail-open in the child)."""
    def _boom(_n):
        raise PermissionError("EPERM")

    monkeypatch.setattr(dt.os, "nice", _boom, raising=False)
    fn = dt.nice_preexec()
    assert callable(fn)
    fn()  # the PermissionError must be swallowed, not propagated


# --- wiring: the prefix flows into task_marketplace_refresh's argv ---------

def _load_daemon():
    """Import scripts/daemon.py with scripts/lib + scripts/oauth_rotator on sys.path.

    daemon.py inserts those at import time; we mirror it so the module loads in
    the test process without spawning the real daemon.
    """
    for p in (_LIB, _PROJECT_ROOT / "scripts" / "oauth_rotator"):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    spec = importlib.util.spec_from_file_location(
        "janitor_daemon_under_test", _PROJECT_ROOT / "scripts" / "daemon.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_lock_ctx():
    import contextlib

    @contextlib.contextmanager
    def _fake_lock():
        yield True

    return _fake_lock


def _stub_plan_of_one(daemon, monkeypatch, name="only-mkt"):
    """Give task_marketplace_refresh a one-marketplace plan without touching the
    real installed_plugins.json (the planner itself is exercised separately, in
    test_marketplace_refresh_plan.py — this test is about throttle wiring)."""
    monkeypatch.setattr(daemon, "_plugins_cache_root", lambda: __import__("pathlib").Path("/nonexistent/cache"))
    monkeypatch.setattr(daemon.mrp, "refresh_plan", lambda installed, extra: [name])


def test_marketplace_refresh_applies_prefix_when_available(monkeypatch):
    """task_marketplace_refresh prepends the throttle prefix and passes a preexec
    when launchers are present — proving the throttle is wired to the per-item
    subprocess call."""
    daemon = _load_daemon()
    captured: dict = {}

    # Pretend the host is Linux with both launchers so the prefix is non-empty.
    monkeypatch.setattr(daemon.dt, "_low_priority_prefix", lambda: ["nice", "-n", "19", "ionice", "-c", "3"])
    sentinel = lambda: None  # noqa: E731 — a stand-in preexec callable
    monkeypatch.setattr(daemon.dt, "nice_preexec", lambda: sentinel)
    monkeypatch.setattr(daemon.gs, "marketplace_lock", _fake_lock_ctx())
    _stub_plan_of_one(daemon, monkeypatch)

    # Capture what argv + preexec the per-item workload call receives; do not spawn.
    def _fake_run_workload_once(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["preexec"] = kwargs.get("preexec_fn")
        return daemon.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(daemon, "_run_workload_once", _fake_run_workload_once)
    monkeypatch.setattr(daemon.state, "log_line", lambda *a, **k: None)

    daemon.task_marketplace_refresh()

    assert captured["cmd"] == [
        "nice", "-n", "19", "ionice", "-c", "3",
        "claude", "plugin", "marketplace", "update", "only-mkt",
    ]
    assert captured["preexec"] is sentinel


def test_marketplace_refresh_falls_back_when_no_throttle(monkeypatch):
    """With no launchers AND no preexec, the bare per-item command is run
    un-throttled — the FAIL-OPEN behavior that keeps the daemon working everywhere."""
    daemon = _load_daemon()
    captured: dict = {}

    monkeypatch.setattr(daemon.dt, "_low_priority_prefix", lambda: [])
    monkeypatch.setattr(daemon.dt, "nice_preexec", lambda: None)
    monkeypatch.setattr(daemon.gs, "marketplace_lock", _fake_lock_ctx())
    _stub_plan_of_one(daemon, monkeypatch)

    def _fake_run_workload_once(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["preexec"] = kwargs.get("preexec_fn")
        return daemon.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(daemon, "_run_workload_once", _fake_run_workload_once)
    monkeypatch.setattr(daemon.state, "log_line", lambda *a, **k: None)

    daemon.task_marketplace_refresh()

    assert captured["cmd"] == ["claude", "plugin", "marketplace", "update", "only-mkt"]
    assert captured["preexec"] is None


def test_marketplace_refresh_throttle_build_error_falls_back(monkeypatch):
    """If building the throttle prefix raises, the task still runs the bare
    per-item command (a throttle bug never breaks marketplace-refresh)."""
    daemon = _load_daemon()
    captured: dict = {}

    def _boom():
        raise RuntimeError("throttle build blew up")

    monkeypatch.setattr(daemon.dt, "_low_priority_prefix", _boom)
    monkeypatch.setattr(daemon.dt, "nice_preexec", lambda: None)
    monkeypatch.setattr(daemon.gs, "marketplace_lock", _fake_lock_ctx())
    _stub_plan_of_one(daemon, monkeypatch)

    def _fake_run_workload_once(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["preexec"] = kwargs.get("preexec_fn")
        return daemon.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(daemon, "_run_workload_once", _fake_run_workload_once)
    monkeypatch.setattr(daemon.state, "log_line", lambda *a, **k: None)

    daemon.task_marketplace_refresh()

    assert captured["cmd"] == ["claude", "plugin", "marketplace", "update", "only-mkt"]
    assert captured["preexec"] is None
