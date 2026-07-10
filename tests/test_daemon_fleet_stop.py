"""Daemon fleet-stop beat (TRDD-ME8V2YJF) — task_fleet_stop end-to-end decision test.

Real global-state I/O (isolated dir) + real flag setters, but the fleet scan, the
channel builder, and the FIRE are stubbed so the test never spawns a process or types
a keystroke. Pins: opt-in-off is inert, flag-none clears stamps, a set flag injects
the stop command into every OTHER session (never self/daemon/user-active), dedupe,
and no-stamp-on-fire-failure.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent.parent / "scripts" / "lib"
sys.path.insert(0, str(_LIB))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
fleet_scan = importlib.import_module("fleet_scan")
daemon = importlib.import_module("daemon")
gs = importlib.import_module("global_state")


def _inst(pid: int, *, active: bool = False, command: str = "claude") -> object:
    return fleet_scan.Instance(
        pid=pid, command=command, tty=f"ttys{pid:03d}", project_root=f"/proj/{pid}",
        terminal={"tmux_pane": f"%{pid}"}, diagnosis="healthy", recovery=None,
        dispatch_age_s=None, active=active, transcript_age_s=10,
    )


class _Fire:
    def __init__(self, result: bool = True) -> None:
        self.calls: list[dict] = []
        self.result = result

    def __call__(self, plan: dict) -> bool:
        self.calls.append(plan)
        return self.result


def _wire(monkeypatch, tmp_path, *, fleet, enabled=True, fire_ok=True, plan: str | None = "ok"):
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FLEET_STOP_ENABLED", "1" if enabled else "0")
    monkeypatch.setattr(daemon.fleet_scan, "gather_fleet", lambda *, now: fleet)
    monkeypatch.setattr(daemon.gs, "daemon_pid", lambda: 2)
    monkeypatch.setattr(daemon.os, "getpid", lambda: 1)

    def _plan(terminal, command, *, esc_first):
        # SOFT contract (TRDD-0GPQROC1): a fleet stop lands at each session's turn
        # boundary — the daemon must never request an ESC-interrupt here.
        assert esc_first is False, "fleet-stop injection must be soft (no ESC)"
        return None if plan is None else {"channel": "tmux", "command": command}

    monkeypatch.setattr(daemon.fleet_restart, "command_injection_plan", _plan)
    fire = _Fire(fire_ok)
    monkeypatch.setattr(daemon.fleet_inject, "fire", fire)
    return fire


def test_inert_when_opt_in_off(monkeypatch, tmp_path) -> None:
    """With the opt-in off, the beat fires nothing even though a disarm flag is set."""
    fire = _wire(monkeypatch, tmp_path, fleet=[_inst(10)], enabled=False)
    gs.set_kill_switch("d")
    daemon.task_fleet_stop()
    assert fire.calls == []


def test_no_flag_clears_stamps(monkeypatch, tmp_path) -> None:
    """No fleet-stop flag → the beat clears any stamps and fires nothing."""
    fire = _wire(monkeypatch, tmp_path, fleet=[_inst(10)])
    gs.record_fleet_injection(10, "disarm", now=1)
    daemon.task_fleet_stop()
    assert fire.calls == []
    assert gs.fleet_injections_seen() == set()


def test_disarm_injects_all_others(monkeypatch, tmp_path) -> None:
    """A disarm flag injects /janitor-disarm into every clean OTHER session and stamps."""
    fleet = [_inst(1), _inst(2), _inst(40, active=True), _inst(41), _inst(42)]
    fire = _wire(monkeypatch, tmp_path, fleet=fleet)
    gs.set_kill_switch("d")
    daemon.task_fleet_stop()
    fired_cmds = {c["command"] for c in fire.calls}
    assert fired_cmds == {"/janitor-disarm"}
    # only 41 + 42: 1=self, 2=daemon, 40=user-active
    assert len(fire.calls) == 2
    assert gs.fleet_injections_seen() == {"41:disarm", "42:disarm"}


def test_dedupe_skips_already_injected(monkeypatch, tmp_path) -> None:
    """An already-stamped (pid, flag) is not re-fired on the next beat."""
    fire = _wire(monkeypatch, tmp_path, fleet=[_inst(41), _inst(42)])
    gs.set_kill_switch("d")
    gs.record_fleet_injection(41, "disarm", now=1)
    daemon.task_fleet_stop()
    assert len(fire.calls) == 1
    assert gs.fleet_injections_seen() == {"41:disarm", "42:disarm"}


def test_pause_injects_pause_command(monkeypatch, tmp_path) -> None:
    """A pause flag (no kill-switch) injects /janitor-pause."""
    fire = _wire(monkeypatch, tmp_path, fleet=[_inst(41)])
    gs.set_global_pause("p")
    daemon.task_fleet_stop()
    assert [c["command"] for c in fire.calls] == ["/janitor-pause"]


def test_no_stamp_on_fire_failure(monkeypatch, tmp_path) -> None:
    """A failed fire records NO stamp, so the next beat retries that session."""
    fire = _wire(monkeypatch, tmp_path, fleet=[_inst(41)], fire_ok=False)
    gs.set_kill_switch("d")
    daemon.task_fleet_stop()
    assert len(fire.calls) == 1
    assert gs.fleet_injections_seen() == set()


def test_unreachable_channel_skipped(monkeypatch, tmp_path) -> None:
    """A session with no resolvable channel (plan None) is skipped, not stamped."""
    fire = _wire(monkeypatch, tmp_path, fleet=[_inst(41)], plan=None)
    gs.set_kill_switch("d")
    daemon.task_fleet_stop()
    assert fire.calls == []
    assert gs.fleet_injections_seen() == set()
