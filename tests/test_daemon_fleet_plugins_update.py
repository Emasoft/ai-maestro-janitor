"""Tests for the daemon's fleet-plugins-update task (scripts/daemon.py).

`task_fleet_plugins_update` is the fleet-wide sibling of `task_user_plugins_update`: it
delegates to `fleet_plugin_updates.sweep()` to update every enabled PROJECT/LOCAL-scope
plugin across every project on the machine, not just the currently-open one. These are
lightweight in-process unit tests (module imported directly, `fpu.sweep` / `gs.marketplace_lock`
monkeypatched) — no real `claude` subprocess, no real marketplace lock file. The heavier
subprocess-level daemon tests live in test_daemon.py.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DAEMON = _PROJECT_ROOT / "scripts" / "daemon.py"

sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


def _import_daemon_module():
    """Import scripts/daemon.py as a module so we can call its helpers directly.

    Mirrors test_daemon.py's `_import_daemon_module` — the shebang + PEP 723 block is
    harmless inside Python's import path; only `if __name__ == '__main__'` is skipped.
    """
    import importlib.util as _u
    spec = _u.spec_from_file_location("janitor_daemon_under_test_fleet_plugins", str(_DAEMON))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fleet_plugins_update_registered_at_6h() -> None:
    """_build_tasks() includes fleet-plugins-update, on the bulk lane, at the 6 h cadence."""
    daemon = _import_daemon_module()
    tasks = {t.name: t for t in daemon._build_tasks()}
    assert "fleet-plugins-update" in tasks
    task = tasks["fleet-plugins-update"]
    assert task.interval_s == 21600
    assert task.fn is daemon.task_fleet_plugins_update
    assert task.background is True, "a fleet-wide sweep is bulk work — must run on the bulk lane"


@contextlib.contextmanager
def _fake_lock(got: bool):
    yield got


def test_fleet_plugins_update_calls_sweep_under_the_marketplace_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The happy path: the lock is acquired, sweep() runs, and its result decides the reload flag."""
    daemon = _import_daemon_module()
    calls: list[str] = []
    monkeypatch.setattr(daemon.fpu, "sweep", lambda: (calls.append("swept") or ["p@mp"]))
    monkeypatch.setattr(daemon.gs, "marketplace_lock", lambda: _fake_lock(True))
    reload_calls: list[str] = []
    monkeypatch.setattr(daemon.gs, "set_reload_flag", lambda reason: reload_calls.append(reason))
    monkeypatch.setattr(daemon.state, "log_line", lambda *_a, **_k: None)

    daemon.task_fleet_plugins_update()

    assert calls == ["swept"], "the task must delegate to fleet_plugin_updates.sweep()"
    assert reload_calls == ["p@mp"], "an updated plugin id must set the reload-needed flag"


def test_fleet_plugins_update_noop_when_sweep_reports_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sweep() returning no updated ids must never touch the reload flag."""
    daemon = _import_daemon_module()
    monkeypatch.setattr(daemon.fpu, "sweep", lambda: [])
    monkeypatch.setattr(daemon.gs, "marketplace_lock", lambda: _fake_lock(True))
    reload_calls: list[str] = []
    monkeypatch.setattr(daemon.gs, "set_reload_flag", lambda reason: reload_calls.append(reason))
    monkeypatch.setattr(daemon.state, "log_line", lambda *_a, **_k: None)

    daemon.task_fleet_plugins_update()

    assert reload_calls == [], "no updates → no reload flag"


def test_fleet_plugins_update_defers_when_lock_is_held(monkeypatch: pytest.MonkeyPatch) -> None:
    """Another marketplace op holding the lock must skip sweep() entirely — never race it."""
    daemon = _import_daemon_module()
    calls: list[str] = []
    monkeypatch.setattr(daemon.fpu, "sweep", lambda: (calls.append("swept") or ["p@mp"]))
    monkeypatch.setattr(daemon.gs, "marketplace_lock", lambda: _fake_lock(False))
    reload_calls: list[str] = []
    monkeypatch.setattr(daemon.gs, "set_reload_flag", lambda reason: reload_calls.append(reason))
    monkeypatch.setattr(daemon.state, "log_line", lambda *_a, **_k: None)

    daemon.task_fleet_plugins_update()

    assert calls == [], "sweep() must never run without the marketplace lock"
    assert reload_calls == []
