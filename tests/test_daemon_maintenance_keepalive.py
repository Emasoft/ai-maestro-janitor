"""INVERTED — the maintenance-branch OAuth keepalive (B3) has no bug left to guard.

Original bug: the daemon's global-MAINTENANCE branch in main() `continue`d straight past the
ENTIRE task list, so "oauth-rotator-tick" (the 60 s beat that refreshes the LIVE OAuth
credential) never fired while the fleet was in maintenance — even though sessions kept firing
("daemon idles, sessions keep firing CHEAP"), so the live token could lapse under the fleet's
nose. The fix was `_run_maintenance_keepalive()`: a second, parallel task-dispatch path that
ran ONLY the names in `_MAINTENANCE_KEEPALIVE_TASK_NAMES`.

Maintenance mode is gone (owner directive 2026-07-31), and with it both the branch and its
carve-out. That is the stronger fix: the bug existed BECAUSE there were two dispatch paths and
one of them silently dropped survival work. Now there is one loop, every task is gated only by
its own cadence, and no mode can skip it.

These tests are kept, not deleted, because the failure they describe is easy to re-create: the
next person who adds a "cheap mode" will reach for a task allowlist, and an allowlist is how
oauth-rotator-tick got dropped the first time. They assert the second path stays gone, and that
the real task roster still carries the beat that used to need rescuing.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_LIB = Path(__file__).resolve().parent.parent / "scripts" / "lib"
sys.path.insert(0, str(_LIB))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
daemon = importlib.import_module("daemon")
gs = importlib.import_module("global_state")


@pytest.fixture(autouse=True)
def _isolate_janitor_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect every janitor global-state / DATA / HOME path to a per-test tmp tree so no
    test here can read or write the real ~/.claude/janitor-global-state/ or the real plugin
    DATA dir (TRDD-ZNN0UK5K)."""
    home = tmp_path / "_home"
    data = home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"
    gsd = tmp_path / "_global-state"
    for d in (home, data, gsd):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)


def test_the_second_dispatch_path_is_gone() -> None:
    """No keepalive allowlist, no keepalive runner, no flag to enter the mode that needed them.

    All four names are asserted together because any ONE of them surviving is enough to rebuild
    the bug: a list without a runner invites a new runner, and a runner without a flag invites a
    new flag."""
    assert not hasattr(daemon, "_run_maintenance_keepalive")
    assert not hasattr(daemon, "_MAINTENANCE_KEEPALIVE_TASK_NAMES")
    assert not hasattr(gs, "maintenance_mode_present")
    assert not hasattr(gs, "set_maintenance_mode")


def test_the_oauth_beat_is_an_ordinary_task_gated_only_by_its_cadence(monkeypatch, tmp_path) -> None:
    """The beat that used to need rescuing now runs through the SAME `.is_due()`/`.run()` path as
    everything else — which is exactly why no mode can drop it any more. Real `daemon.Task` with
    a spy fn (no subprocess, no network, no keychain), so this exercises the production
    bookkeeping rather than a stand-in."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    calls: list[str] = []
    tick = daemon.Task("oauth-rotator-tick", 60, lambda: calls.append("ran"))

    assert tick.is_due() is True, "fresh — never run before"
    tick.run()
    assert calls == ["ran"]
    assert tick.is_due() is False, "run() stamps the cadence; the beat is not re-run inside 60 s"


def test_the_real_roster_still_carries_the_oauth_beat(monkeypatch, tmp_path) -> None:
    """The survival beat is in `_build_tasks()` itself. With the allowlist gone this is the only
    thing that keeps it running, so it is asserted against the REAL roster — not a fixture."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    names = {t.name for t in daemon._build_tasks()}
    assert "oauth-rotator-tick" in names
