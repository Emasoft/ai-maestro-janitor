"""Maintenance-branch OAuth keepalive (B3 fix) — _run_maintenance_keepalive unit test.

Bug: the daemon's global-MAINTENANCE branch in main() used to `continue` straight past
the ENTIRE task list, so "oauth-rotator-tick" (the 60 s beat that refreshes the LIVE
OAuth credential) never fired while the fleet was in maintenance — even though sessions
keep firing (the CLAUDE.md contract is "daemon idles, sessions keep firing CHEAP"), so
the live token could lapse under the fleet's nose. _run_maintenance_keepalive() is the
extracted, directly-testable fix: it runs ONLY task(s) named in
_MAINTENANCE_KEEPALIVE_TASK_NAMES (today just "oauth-rotator-tick") and leaves every
other task — including the alert-only "oauth-rotator-supervisor" — untouched.

Uses REAL `daemon.Task` objects (spy `fn`s, no real subprocess/network/keychain) so the
assertions exercise the actual `.name` filter + `.is_due()`/`.run()` cadence bookkeeping
`_build_tasks()` would hand the helper in production — not a hand-rolled stand-in.
Isolated via JANITOR_GLOBAL_STATE_DIR (Task's cadence stamps live under the global
state dir) mirroring tests/test_daemon_fleet_stop.py. No real cron, no daemon process,
no live OAuth call.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent.parent / "scripts" / "lib"
sys.path.insert(0, str(_LIB))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
daemon = importlib.import_module("daemon")
gs = importlib.import_module("global_state")


def _wire(monkeypatch, tmp_path) -> None:
    """Isolate global state + establish the realistic maintenance/opted-in scenario.

    The maintenance flag and the rotator opt-in are the real-world PRECONDITIONS this
    bug occurs under (see the module docstring); _run_maintenance_keepalive() itself
    trusts its caller's maintenance check and never touches opt_in_present() directly
    (that gate lives inside the real task_oauth_rotator_tick fn, which these tests
    replace with a spy), so setting them up here documents the scenario and protects
    a future test that wires the real task fn instead of a spy.
    """
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(daemon.oauth_supervisor, "opt_in_present", lambda *_a, **_k: True)
    gs.set_maintenance_mode("test")
    assert gs.maintenance_mode_present() is True


def test_runs_oauth_tick_when_due_and_skips_non_keepalive_task(monkeypatch, tmp_path) -> None:
    """A due 'oauth-rotator-tick' Task runs; a due non-keepalive Task does not."""
    _wire(monkeypatch, tmp_path)
    tick_calls: list[str] = []
    other_calls: list[str] = []
    tick_task = daemon.Task("oauth-rotator-tick", 60, lambda: tick_calls.append("ran"))
    other_task = daemon.Task("marketplace-refresh", 60, lambda: other_calls.append("ran"))
    assert tick_task.is_due() is True  # fresh — never run before
    assert other_task.is_due() is True

    daemon._run_maintenance_keepalive([tick_task, other_task])

    assert tick_calls == ["ran"], "the keepalive task must run"
    assert other_calls == [], "a non-keepalive task must NOT run under maintenance"
    # Task.run() stamps last-run.ts — proves the cadence bookkeeping still applies.
    assert tick_task.is_due() is False, "run() must stamp the cadence like a normal tick"


def test_skips_oauth_tick_when_not_yet_due(monkeypatch, tmp_path) -> None:
    """A just-run 'oauth-rotator-tick' Task (inside its 60 s cadence) is NOT re-run."""
    _wire(monkeypatch, tmp_path)
    calls: list[str] = []
    tick_task = daemon.Task("oauth-rotator-tick", 60, lambda: calls.append("ran"))
    tick_task.run()  # stamps last-run.ts to "now" — not due again for 60 s
    calls.clear()

    daemon._run_maintenance_keepalive([tick_task])

    assert calls == [], "must respect the Task's own cadence, not run unconditionally"


def test_empty_or_non_matching_task_list_is_a_safe_no_op(monkeypatch, tmp_path) -> None:
    """No tasks, or tasks with no keepalive name, never raise and never run anything."""
    _wire(monkeypatch, tmp_path)
    calls: list[str] = []
    other_task = daemon.Task("version-update", 60, lambda: calls.append("ran"))

    daemon._run_maintenance_keepalive([])
    daemon._run_maintenance_keepalive([other_task])

    assert calls == []
