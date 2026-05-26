"""Tests for scripts/daemon.py — the global single-instance daemon.

The daemon is exercised as a subprocess (the real invocation surface). Tests
isolate per-tmp_path: JANITOR_GLOBAL_STATE_DIR points at a fresh dir so the
user's real ~/.claude/janitor-global-state/ is never touched. `claude` is
stubbed via a PATH shim (a small Python script) so no real plugin update
or marketplace fetch ever runs; the stub logs each call so tests can assert
exactly which CLI subcommands the daemon invoked.

Cadence intervals are forced to 1 second via env so the daemon fires its
tasks within the test's wait window without us having to mock time.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DAEMON = _PROJECT_ROOT / "scripts" / "daemon.py"

assert _DAEMON.is_file(), f"daemon not found at {_DAEMON}"


# Stub `claude`: dispatches on argv, logs every invocation, returns canned
# responses for the three subcommands the daemon uses.
_CLAUDE_STUB = '''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
log = os.environ.get("CLAUDE_STUB_LOG", "")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(" ".join(a) + "\\n")
if a[:3] == ["plugin", "marketplace", "update"]:
    sys.stdout.write("Updated 1 marketplace.\\n")
    raise SystemExit(0)
if a[:3] == ["plugin", "list", "--json"]:
    payload = [
        {"id": "test-plugin-a@mp", "scope": "user", "enabled": True},
        {"id": "test-plugin-b@mp", "scope": "user", "enabled": False},
        {"id": "test-plugin-c@mp", "scope": "local", "enabled": True},
    ]
    sys.stdout.write(json.dumps(payload))
    raise SystemExit(0)
if a[:2] == ["plugin", "update"]:
    raise SystemExit(0)
sys.stderr.write("claude-stub: unhandled %r\\n" % (a,))
raise SystemExit(99)
'''


@pytest.fixture
def harness(tmp_path: Path):
    """Set up the daemon's isolated runtime: state dir + stub claude on PATH.

    Yields a dict with paths the test needs. Tears down any spawned daemon
    by SIGKILL'ing PIDs it produced so a flaky assertion can never leave a
    real daemon process behind.
    """
    state_dir = tmp_path / "state"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text(_CLAUDE_STUB, encoding="utf-8")
    (bin_dir / "claude").chmod(0o755)
    stub_log = tmp_path / "claude.log"

    base_env = os.environ.copy()
    base_env["JANITOR_GLOBAL_STATE_DIR"] = str(state_dir)
    base_env["PATH"] = f"{bin_dir}{os.pathsep}{base_env['PATH']}"
    base_env["CLAUDE_STUB_LOG"] = str(stub_log)
    # Fire tasks every second during tests so the assertion window is short.
    base_env["CLAUDE_PLUGIN_OPTION_DAEMON_MARKETPLACE_REFRESH_INTERVAL"] = "1"
    base_env["CLAUDE_PLUGIN_OPTION_DAEMON_USER_PLUGINS_UPDATE_INTERVAL"] = "1"

    spawned: list[subprocess.Popen[bytes]] = []

    def spawn() -> subprocess.Popen[bytes]:
        # Invoke via the shebang (`uv run --script --quiet`); uv is on PATH on
        # any host running these tests (uvx is what's running pytest itself).
        proc = subprocess.Popen(
            [str(_DAEMON)],
            env=base_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        spawned.append(proc)
        return proc

    yield {
        "state_dir": state_dir,
        "bin_dir": bin_dir,
        "stub_log": stub_log,
        "env": base_env,
        "spawn": spawn,
    }

    # Teardown: terminate any daemons the test (or its singleton-loser
    # siblings) left alive. Best-effort, then SIGKILL the holdouts.
    for proc in spawned:
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass


def _wait_for(predicate, timeout: float = 8.0, interval: float = 0.1) -> bool:
    """Poll until `predicate()` returns truthy, or timeout. Return its value."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = predicate()
        if v:
            return v
        time.sleep(interval)
    return predicate()


def _read_pid(pid_path: Path) -> Optional[int]:
    if not pid_path.is_file():
        return None
    try:
        return int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def test_daemon_writes_pid_and_heartbeat(harness: dict) -> None:
    """Daemon writes its pid file and heartbeat ts shortly after startup."""
    harness["spawn"]()  # fixture keeps the Popen ref alive for teardown
    pid_path = harness["state_dir"] / "daemon.pid"
    hb_path = harness["state_dir"] / "daemon.heartbeat.ts"

    assert _wait_for(lambda: pid_path.is_file() and hb_path.is_file()), \
        "pid + heartbeat files must appear within 8 s"
    written_pid = _read_pid(pid_path)
    assert written_pid is not None
    assert _alive(written_pid), "the PID in daemon.pid must be a live process"
    # The pid written by the daemon is its OWN process; with the `uv run`
    # shebang the daemon is a python child of the uv launcher (proc.pid),
    # so written_pid ≠ proc.pid in general but both are alive.


def test_daemon_runs_marketplace_refresh_and_user_plugins_update(harness: dict) -> None:
    """Within the first cadence window the daemon invokes both tasks' CLI calls."""
    harness["spawn"]()
    stub_log = harness["stub_log"]

    # Wait for the stub log to contain BOTH marketplace update and at least
    # one user-scope plugin update (proves user-plugins-update enumerated
    # and filtered the list, then dispatched the per-plugin update).
    def saw_both() -> bool:
        if not stub_log.is_file():
            return False
        lines = stub_log.read_text(encoding="utf-8").splitlines()
        return any("plugin marketplace update" in ln for ln in lines) and \
               any("plugin update test-plugin-a@mp --scope user" in ln for ln in lines)

    assert _wait_for(saw_both, timeout=10.0), "daemon must run both tasks"

    # Sanity: the local-scope plugin in the stub list must NOT have been
    # updated by the daemon (user-scope is the daemon's job, not local-scope).
    lines = stub_log.read_text(encoding="utf-8").splitlines()
    assert not any("plugin update test-plugin-c@mp" in ln for ln in lines), \
        "local-scope plugin must be filtered out by the daemon"


def test_daemon_singleton_second_spawn_exits(harness: dict) -> None:
    """Two parallel spawns → only one acquires the flock; the second exits."""
    p1 = harness["spawn"]()
    pid_path = harness["state_dir"] / "daemon.pid"
    assert _wait_for(lambda: pid_path.is_file()), "first daemon must write pid"
    first_pid = _read_pid(pid_path)
    assert first_pid is not None

    # Second spawn — must exit silently because flock is held by the first.
    p2 = harness["spawn"]()
    # p2 is the `uv run` launcher PID; we wait for the whole process tree to
    # exit by polling its returncode.
    assert _wait_for(lambda: p2.poll() is not None, timeout=10.0), \
        "second daemon must exit because the flock is held"

    # The pid file must STILL reference the first daemon (not overwritten).
    assert _read_pid(pid_path) == first_pid

    # And the first daemon must still be alive.
    assert _alive(first_pid)
    _ = p1  # keep ref for teardown


def test_daemon_kill_switch_exits(harness: dict) -> None:
    """Touching kill-switch.flag makes the running daemon exit gracefully."""
    p = harness["spawn"]()
    pid_path = harness["state_dir"] / "daemon.pid"
    assert _wait_for(lambda: pid_path.is_file()), "daemon must start"
    pid = _read_pid(pid_path)
    assert pid is not None

    # Trip the kill switch.
    (harness["state_dir"] / "kill-switch.flag").touch()

    # Daemon should exit within one loop ceiling (~60 s); the daemon ticks
    # in 1-second increments so this is generally < 3 s in practice.
    assert _wait_for(lambda: not _alive(pid), timeout=15.0), \
        "daemon must observe kill-switch and exit"
    # PID file should be cleaned up.
    assert _wait_for(lambda: not pid_path.is_file(), timeout=5.0), \
        "graceful shutdown must remove daemon.pid"
    _ = p


def test_daemon_sigterm_graceful_shutdown(harness: dict) -> None:
    """SIGTERM to the daemon triggers graceful exit + cleanup."""
    p = harness["spawn"]()
    pid_path = harness["state_dir"] / "daemon.pid"
    assert _wait_for(lambda: pid_path.is_file()), "daemon must start"
    pid = _read_pid(pid_path)
    assert pid is not None

    # SIGTERM the daemon process directly.
    os.kill(pid, signal.SIGTERM)

    assert _wait_for(lambda: not _alive(pid), timeout=15.0), \
        "daemon must exit on SIGTERM"
    assert _wait_for(lambda: not pid_path.is_file(), timeout=5.0), \
        "graceful shutdown removes the pid file"
    _ = p


def test_daemon_marks_last_run_after_task(harness: dict) -> None:
    """Each task records its last-run.ts on completion."""
    _ = harness["spawn"]()
    mr_path = harness["state_dir"] / "marketplace-refresh.last-run.ts"
    up_path = harness["state_dir"] / "user-plugins-update.last-run.ts"

    assert _wait_for(lambda: mr_path.is_file() and up_path.is_file(), timeout=10.0), \
        "both task last-run files must be written"
    # Stamps must be sensible epoch seconds (within the last minute).
    now = int(time.time())
    for p in (mr_path, up_path):
        ts = int(p.read_text(encoding="utf-8").strip())
        assert abs(now - ts) < 60, f"stamp {ts} unreasonably far from now {now}"
