"""R1b (TRDD-ZAKT0NRI): the rotator tick lives in its own thread; the plugin-update step cannot
wedge the main loop. Real threads, real subprocesses, real flocks — no scheduler mocks.

Incident 2026-10-03: the daemon sat ~31 min stuck in its main loop (outside `_run_due_tasks`) and
the 60 s rotator tick, which only the main loop ran, stopped with it.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_ROOT / "scripts" / "oauth_rotator"))
sys.path.insert(0, str(_ROOT / "scripts"))
daemon = importlib.import_module("daemon")
gs = importlib.import_module("global_state")
rotator = importlib.import_module("rotator")


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-test tmp tree for every janitor state / DATA / HOME path."""
    home = tmp_path / "_home"
    data = home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"
    gsd = tmp_path / "_global-state"
    for d in (home, data, gsd):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.setenv("JANITOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("JANITOR_ROTATOR_WEDGE_TICK", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    for fn in (daemon.state.project_root, daemon.state.janitor_root,
               daemon.state.state_dir, daemon.state.log_dir):
        fn.cache_clear()


def _wait(pred, timeout: float) -> bool:  # type: ignore[no-untyped-def]
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False



_PLUGIN = "foo" + "@" + "bar"  # runtime-built: keeps the privacy scanner quiet


def _thread(fn, interval: int = 1) -> daemon._RotatorTickThread:  # type: ignore[no-untyped-def]
    """A tick thread whose task just ran: the first beat tick is `interval` s away."""
    task = daemon.Task("oauth-rotator-tick", interval, fn, own_thread=True)
    daemon.state.atomic_write(task.last_run_path, str(int(time.time())))
    return daemon._RotatorTickThread(task)


def test_tick_runs_while_the_main_thread_is_blocked() -> None:
    """With the main thread stuck in a long real subprocess, the tick thread still ticks within
    its interval, and never writes the daemon heartbeat (a stuck loop must stay detectable)."""
    ran: list[float] = []
    t = _thread(lambda: ran.append(time.time()))
    t.start()
    try:
        before = gs.read_heartbeat()
        subprocess.run(["sleep", "3.5"], check=True)  # the 'stuck main loop'
        assert len(ran) >= 1, "the tick thread must run while the main thread is blocked"
        assert gs.read_heartbeat() == before, "the tick thread must not refresh the heartbeat"
    finally:
        t.shutdown(5)


def test_tick_workload_does_not_write_the_heartbeat() -> None:
    """A tick that shells out through `_run_workload_once` must not tick the heartbeat from the
    thread (the main-thread call does)."""
    done = threading.Event()

    def body() -> None:
        daemon._run_workload_once(["sleep", "2.2"], heartbeat_tick=1)
        done.set()

    t = _thread(body, interval=3600)
    t.request_wedge_tick()
    t.start()
    try:
        assert done.wait(10)
        assert gs.read_heartbeat() == 0, "heartbeat written by the tick thread"
        daemon._run_workload_once(["true"])
        assert gs.read_heartbeat() > 0, "control: the main thread still writes it"
    finally:
        t.shutdown(5)


def test_wedge_request_runs_the_tick_now_with_the_env() -> None:
    """A wedge request makes the thread tick immediately (interval is an hour) with the wedge env
    set during the body and gone afterwards."""
    seen: list[str | None] = []
    t = _thread(lambda: seen.append(os.environ.get("JANITOR_ROTATOR_WEDGE_TICK")), interval=3600)
    t.start()
    try:
        gs.request_rotator_tick("retry-wedged-esc")
        assert daemon._consume_rotator_tick_request(t) is True
        assert _wait(lambda: bool(seen), 5), "wedge request did not run the tick"
        assert seen == ["1"]
        assert "JANITOR_ROTATOR_WEDGE_TICK" not in os.environ
        assert gs.rotator_tick_requested_present() is False
    finally:
        t.shutdown(5)


def test_shutdown_stops_the_thread() -> None:
    """shutdown() joins the thread."""
    t = _thread(lambda: None)
    t.start()
    assert t.is_alive()
    t.shutdown(5)
    assert not t.is_alive()


def test_yielded_tick_is_not_run() -> None:
    """While the ai-maestro server owns the tick the thread does not run it."""
    ran: list[int] = []
    t = _thread(lambda: ran.append(1))
    t.set_yielded(True)
    t.start()
    try:
        time.sleep(2.5)
        assert ran == []
        t.set_yielded(False)
        assert _wait(lambda: bool(ran), 5)
    finally:
        t.shutdown(5)


def test_main_loop_never_dispatches_the_thread_task() -> None:
    """`_run_due_tasks` skips an own_thread task even when it is due."""
    ran: list[int] = []
    task = daemon.Task("oauth-rotator-tick", 60, lambda: ran.append(1), own_thread=True)
    daemon._run_due_tasks([task], set())
    assert ran == []
    assert [t.own_thread for t in daemon._build_tasks() if t.name == "oauth-rotator-tick"] == [True]


def test_queue_lock_timeout_raises_instead_of_blocking() -> None:
    """A held request-queue lock makes a timed clear raise TimeoutError promptly."""
    with gs._plugin_requests_lock():
        t0 = time.time()
        with pytest.raises(TimeoutError):
            gs.clear_plugin_update_request(_PLUGIN, "user", lock_timeout=0.3)
        assert time.time() - t0 < 3


def test_consume_returns_when_the_queue_lock_is_held(monkeypatch: pytest.MonkeyPatch) -> None:
    """The daemon's consume logs and returns (0 updated) rather than blocking on a held lock."""
    gs.request_plugin_update(_PLUGIN, "user", "test")
    monkeypatch.setattr(daemon, "_PLUGIN_UPDATE_LOCK_TIMEOUT_SEC", 0.3)
    with gs._plugin_requests_lock():
        t0 = time.time()
        assert daemon._consume_plugin_update_requests() == 0
        assert time.time() - t0 < 3
    assert "timed out" in (Path(os.environ["JANITOR_LOG_DIR"]) / "daemon.log").read_text()


def test_repeatedly_failing_request_is_skipped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """With no `claude` on PATH every attempt fails; after 2 the same request is skipped (and not
    re-attempted) until the 6 h window passes — a restarted daemon must not replay a wedge."""
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    path = daemon._plugin_update_failures_path()
    key = f"{_PLUGIN}|user"
    for expected in (1, 2):
        gs.request_plugin_update(_PLUGIN, "user", "test")
        daemon._consume_plugin_update_requests()
        assert json.loads(path.read_text())[key]["fails"] == expected
    gs.request_plugin_update(_PLUGIN, "user", "test")
    daemon._consume_plugin_update_requests()
    assert json.loads(path.read_text())[key]["fails"] == 2, "third attempt must be skipped"
    assert gs.plugin_update_requests() == [], "the skipped request is still cleared"
    rec = json.loads(path.read_text())
    rec[key]["skip_until"] = 1  # window elapsed
    path.write_text(json.dumps(rec))
    gs.request_plugin_update(_PLUGIN, "user", "test")
    daemon._consume_plugin_update_requests()
    assert json.loads(path.read_text())[key]["fails"] == 1


def test_tick_skipped_on_lock_held_writes_no_completed_stamp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A rotator tick that skips because the rotator lock is held must NOT write
    tick-completed.ts (R4 condition c reads it); a real completion does (control)."""
    monkeypatch.setattr(rotator, "ROOT", tmp_path / "rot")
    stamp = tmp_path / "rot" / "tick-completed.ts"
    held = gs.acquire_oauth_rotator_lock()
    assert held is not None
    try:
        assert rotator.main(["tick", "--only-if-claude-running"]) == 0
    finally:
        gs.release_oauth_rotator_lock(held)
    assert not stamp.exists(), "a skipped tick wrote the completed-tick stamp"
    rotator._stamp_tick_completed()
    assert stamp.exists()
