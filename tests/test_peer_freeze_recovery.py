"""Tests for the peer-freeze-recovery detector (TRDD-KQ9WM4TZ).

The dark-window gate is the whole feature: the beat may run ONLY when the daemon is dead
AND an ai-maestro server is alive. Every other combination must be a cheap no-op with the
outcome named — a guardian that fires in the wrong window is either a second daemon
(the corruption 5ZVS1DDP forbids) or a stampede.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


@pytest.fixture()
def det(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Import the dashed detector fresh, with global state + project isolated."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "proj"))
    (tmp_path / "proj").mkdir()
    spec = importlib.util.spec_from_file_location(
        "peer_freeze_recovery",
        _PROJECT_ROOT / "scripts" / "detectors" / "peer-freeze-recovery.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    # Fresh state module caches (project_root is env-derived per call in state.py, but
    # global_state resolves dirs at call time — nothing to reset beyond env).
    return mod


def _arm_dark_window(det, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(det.gs, "daemon_is_alive", lambda *a, **k: False)
    monkeypatch.setattr(det.harness_backend, "server_is_alive", lambda **k: True)
    monkeypatch.setattr(det.harness_backend, "is_harness_session", lambda *a, **k: False)


def test_noop_when_daemon_alive(det, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(det.harness_backend, "is_harness_session", lambda *a, **k: False)
    monkeypatch.setattr(det.gs, "daemon_is_alive", lambda *a, **k: True)
    assert det.run_once() == "daemon-owns-it"


def test_noop_when_no_server(det, monkeypatch: pytest.MonkeyPatch) -> None:
    """Daemon dead + server dead = the ordinary respawn path's problem, never ours —
    duplicating ensure_daemon_running here would bypass its crash-loop breaker."""
    monkeypatch.setattr(det.harness_backend, "is_harness_session", lambda *a, **k: False)
    monkeypatch.setattr(det.gs, "daemon_is_alive", lambda *a, **k: False)
    monkeypatch.setattr(det.harness_backend, "server_is_alive", lambda **k: False)
    assert det.run_once() == "no-server"


def test_noop_in_harness_session(det, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(det.harness_backend, "is_harness_session", lambda *a, **k: True)
    assert det.run_once() == "harness"


def test_opt_out(det, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_PEER_RECOVERY_ENABLED", "0")
    assert det.run_once() == "disabled"


def test_dark_window_runs_beat_over_peers_only(det, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """In the dark window the daemon's own beat runs over the fleet MINUS this session's
    project — self-recovery from inside the session is the splice hazard TRDD-0BVF4K7E
    closed, and this cron is provably alive (it just ran the detector)."""
    _arm_dark_window(det, monkeypatch)
    me = str(tmp_path / "proj")
    peers = [
        SimpleNamespace(project_root=me),
        SimpleNamespace(project_root=str(tmp_path / "other")),
        SimpleNamespace(project_root=""),
    ]
    seen: dict = {}
    import daemon as daemon_mod
    import fleet_scan as fleet_scan_mod

    monkeypatch.setattr(fleet_scan_mod, "gather_fleet", lambda **k: peers)
    monkeypatch.setattr(daemon_mod, "task_session_liveness", lambda fleet: seen.setdefault("fleet", fleet))
    out = det.run_once(now=int(time.time()))
    assert out == "ran"
    assert [i.project_root for i in seen["fleet"]] == [str(tmp_path / "other")]


def test_machine_wide_pacing_and_stamp_first(det, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A second beat inside the interval is paced out, machine-wide. And the stamp lands
    BEFORE the scan, so even a failing scan paces the fleet instead of every session
    re-crashing it once per heartbeat."""
    _arm_dark_window(det, monkeypatch)
    import fleet_scan as fleet_scan_mod

    def boom(**k):
        raise RuntimeError("scan exploded")

    monkeypatch.setattr(fleet_scan_mod, "gather_fleet", boom)
    now = int(time.time())
    assert det.run_once(now=now) == "scan-failed"
    assert det.run_once(now=now + 10) == "paced", "the failed beat must still have stamped"
    assert det.run_once(now=now + det._interval_s() + 1) == "scan-failed"


def test_no_peers_is_named(det, monkeypatch: pytest.MonkeyPatch) -> None:
    _arm_dark_window(det, monkeypatch)
    import fleet_scan as fleet_scan_mod

    monkeypatch.setattr(fleet_scan_mod, "gather_fleet", lambda **k: [])
    assert det.run_once() == "no-peers"


def test_dispatch_roster_and_harness_denylist() -> None:
    """The detector is armed on the heartbeat AND denied to harness sessions — a roster
    entry without the deny-list line would run fleet actuation inside a server-owned
    agent."""
    import dispatch

    names = [name for name, _, _ in dispatch._DETECTORS]
    assert "peer-freeze-recovery" in names
    assert "peer-freeze-recovery" in dispatch._NON_HARNESS_DETECTORS
