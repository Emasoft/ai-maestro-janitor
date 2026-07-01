"""Fleet-stop flag-state + injection-stamp persistence (TRDD-ME8V2YJF, global_state).

Real I/O against an isolated global-state dir (JANITOR_GLOBAL_STATE_DIR), no mocks.
Drives the flag state through the REAL kill-switch/pause setters so the precedence
(disarm > pause > None) is proven end-to-end, and pins the fail-open dedupe-stamp
round-trip the daemon relies on.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))
gs = importlib.import_module("global_state")


def _isolate(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)


def test_flag_state_none_when_no_flags(monkeypatch, tmp_path: Path) -> None:
    """fleet_stop_flag_state is None when neither the kill-switch nor pause is set."""
    _isolate(monkeypatch, tmp_path)
    gs.clear_kill_switch()
    gs.clear_global_pause()
    assert gs.fleet_stop_flag_state() is None


def test_flag_state_disarm_dominates_pause(monkeypatch, tmp_path: Path) -> None:
    """The kill-switch (disarm) takes precedence over pause when both are set."""
    _isolate(monkeypatch, tmp_path)
    gs.set_global_pause("p")
    assert gs.fleet_stop_flag_state() == "pause"
    gs.set_kill_switch("d")
    assert gs.fleet_stop_flag_state() == "disarm"
    gs.clear_kill_switch()
    assert gs.fleet_stop_flag_state() == "pause"


def test_record_then_seen_roundtrip(monkeypatch, tmp_path: Path) -> None:
    """record_fleet_injection persists a 'pid:flag' key that fleet_injections_seen returns."""
    _isolate(monkeypatch, tmp_path)
    assert gs.fleet_injections_seen() == set()
    gs.record_fleet_injection(4321, "disarm", now=1000)
    gs.record_fleet_injection(4322, "pause", now=1001)
    assert gs.fleet_injections_seen() == {"4321:disarm", "4322:pause"}


def test_seen_fail_open_on_corrupt(monkeypatch, tmp_path: Path) -> None:
    """A corrupt fleet-injections.json yields an empty set, never an exception."""
    _isolate(monkeypatch, tmp_path)
    gs.init_global_state()
    (tmp_path / "fleet-injections.json").write_text("{ not json", encoding="utf-8")
    assert gs.fleet_injections_seen() == set()


def test_clear_all(monkeypatch, tmp_path: Path) -> None:
    """clear_fleet_injections() with no arg forgets every stamp."""
    _isolate(monkeypatch, tmp_path)
    gs.record_fleet_injection(1, "disarm", now=1)
    gs.record_fleet_injection(2, "pause", now=2)
    gs.clear_fleet_injections()
    assert gs.fleet_injections_seen() == set()


def test_clear_per_flag(monkeypatch, tmp_path: Path) -> None:
    """clear_fleet_injections('disarm') forgets only disarm stamps, keeps pause ones."""
    _isolate(monkeypatch, tmp_path)
    gs.record_fleet_injection(1, "disarm", now=1)
    gs.record_fleet_injection(2, "pause", now=2)
    gs.record_fleet_injection(3, "disarm", now=3)
    gs.clear_fleet_injections("disarm")
    assert gs.fleet_injections_seen() == {"2:pause"}


def test_record_is_idempotent_update(monkeypatch, tmp_path: Path) -> None:
    """Re-recording the same (pid, flag) updates its timestamp, not the key set."""
    _isolate(monkeypatch, tmp_path)
    gs.record_fleet_injection(9, "disarm", now=100)
    gs.record_fleet_injection(9, "disarm", now=200)
    assert gs.fleet_injections_seen() == {"9:disarm"}
