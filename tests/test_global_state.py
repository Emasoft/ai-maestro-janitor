"""Tests for scripts/lib/global_state.py — the daemon's shared contract.

These tests exercise the building blocks in-process: directory resolution
respecting `$JANITOR_GLOBAL_STATE_DIR`, exclusive flock semantics, and the
daemon-liveness truth table (no pid / dead pid / stale heartbeat / live +
fresh). Subprocess-level daemon tests live in test_daemon.py.

Per-test isolation: the helper builds a fresh tmp state dir per test, points
JANITOR_GLOBAL_STATE_DIR at it, and reloads global_state to drop any
cached state. Tests use the running pytest PID as a guaranteed-alive PID.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated global state dir per test (no shared ~/.claude/ pollution)."""
    d = tmp_path / "janitor-global-state"
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(d))
    # Force a clean import so the lru-cache / module-state from a previous
    # test cannot leak — global_state itself reads env at call time so this
    # is mostly defensive.
    for mod in ("global_state",):
        if mod in sys.modules:
            del sys.modules[mod]
    return d


def _gs():
    """Import the module fresh after the env is set."""
    import global_state  # type: ignore[import-not-found]
    return global_state


def test_global_state_dir_respects_env_override(state_dir: Path) -> None:
    """$JANITOR_GLOBAL_STATE_DIR overrides the default ~/.claude/... location."""
    assert _gs().global_state_dir() == state_dir.resolve()


def test_init_global_state_creates_dir(state_dir: Path) -> None:
    """init_global_state() is idempotent — calling it twice is safe."""
    _gs().init_global_state()
    _gs().init_global_state()
    assert state_dir.is_dir()


def test_singleton_flock_first_acquires_second_fails(state_dir: Path) -> None:
    """One process holding the flock blocks every other acquire attempt."""
    gs = _gs()
    fd1 = gs.acquire_singleton_flock()
    assert fd1 is not None, "first acquire must succeed"
    try:
        fd2 = gs.acquire_singleton_flock()
        assert fd2 is None, "second acquire must be denied while fd1 holds the lock"
    finally:
        gs.release_singleton_flock(fd1)


def test_singleton_flock_released_lets_next_acquire(state_dir: Path) -> None:
    """Releasing the flock lets a subsequent acquire succeed (no stale state)."""
    gs = _gs()
    fd1 = gs.acquire_singleton_flock()
    assert fd1 is not None
    gs.release_singleton_flock(fd1)
    fd2 = gs.acquire_singleton_flock()
    assert fd2 is not None
    gs.release_singleton_flock(fd2)


def test_daemon_is_alive_no_pid_file(state_dir: Path) -> None:
    """A missing pid file means definitely-not-alive."""
    gs = _gs()
    gs.init_global_state()
    assert gs.daemon_is_alive() is False


def test_daemon_is_alive_dead_pid(state_dir: Path) -> None:
    """A pid file referencing a non-existent PID means not-alive."""
    gs = _gs()
    gs.init_global_state()
    gs.write_daemon_pid(999_999)  # vanishingly unlikely to be a real PID
    gs.write_heartbeat()  # fresh heartbeat is irrelevant when PID is dead
    assert gs.daemon_is_alive() is False


def test_daemon_is_alive_stale_heartbeat(state_dir: Path) -> None:
    """A live PID with a stale heartbeat counts as not-alive (stuck daemon)."""
    gs = _gs()
    gs.init_global_state()
    gs.write_daemon_pid(os.getpid())  # the pytest process itself — surely alive
    gs.write_heartbeat(now=int(time.time()) - (gs.DEFAULT_DAEMON_STALE_SECONDS + 60))
    assert gs.daemon_is_alive() is False


def test_daemon_is_alive_fresh_heartbeat(state_dir: Path) -> None:
    """Live PID + recent heartbeat → alive."""
    gs = _gs()
    gs.init_global_state()
    gs.write_daemon_pid(os.getpid())
    gs.write_heartbeat()
    assert gs.daemon_is_alive() is True


def test_kill_switch_present_detects_flag(state_dir: Path) -> None:
    """Touching kill-switch.flag is the documented disable signal."""
    gs = _gs()
    gs.init_global_state()
    assert gs.kill_switch_present() is False
    (state_dir / "kill-switch.flag").touch()
    assert gs.kill_switch_present() is True


def test_ensure_daemon_running_respects_kill_switch(state_dir: Path) -> None:
    """When kill-switch is set, ensure_daemon_running() never spawns."""
    gs = _gs()
    gs.init_global_state()
    (state_dir / "kill-switch.flag").touch()
    # Should return False (not alive, not spawned).
    assert gs.ensure_daemon_running() is False
    # No PID file should have been created.
    assert not (state_dir / "daemon.pid").exists()


def test_ensure_daemon_running_respects_master_disable(
    state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """daemon_enabled=false silences ensure_daemon_running() entirely."""
    gs = _gs()
    gs.init_global_state()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED", "false")
    assert gs.ensure_daemon_running() is False
    assert not (state_dir / "daemon.pid").exists()


def test_ensure_daemon_running_noop_when_already_alive(state_dir: Path) -> None:
    """A live daemon means ensure_daemon_running() returns True without spawning."""
    gs = _gs()
    gs.init_global_state()
    gs.write_daemon_pid(os.getpid())
    gs.write_heartbeat()
    # Should NOT spawn a real daemon (we can't easily verify negative spawn,
    # but the function should return True quickly).
    assert gs.ensure_daemon_running() is True


def test_daemon_pid_round_trip(state_dir: Path) -> None:
    """write_daemon_pid → daemon_pid returns the exact int."""
    gs = _gs()
    gs.init_global_state()
    gs.write_daemon_pid(12345)
    assert gs.daemon_pid() == 12345
    gs.remove_daemon_pid()
    assert gs.daemon_pid() is None


def test_daemon_pid_malformed_returns_none(state_dir: Path) -> None:
    """A garbled pid file is treated as missing (not-alive)."""
    gs = _gs()
    gs.init_global_state()
    (state_dir / "daemon.pid").write_text("not-a-pid", encoding="utf-8")
    assert gs.daemon_pid() is None
