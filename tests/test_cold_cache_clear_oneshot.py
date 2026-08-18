"""The cold-resume one-shot must record FIRES, not ATTEMPTS.

WHY (measured 2026-08-18). `on-session-start-cold-cache-clear.py` asked "already fired?"
with `dedupe.emit_once(...) is None`, which WRITES the key as a side effect of asking. So
the first SessionStart of a session consumed its single allowance no matter what the
verdict was. This session recorded its key on a run whose verdict was `cache warm` —
nothing cleared — and because a RESUMED session keeps its id indefinitely, every later
reload logged `already fired for this session`. The user restarted after a 24-hour gap
with a certainly-cold cache and still got nothing: the guard is checked BEFORE the cache
check, so the stale key short-circuits a verdict that would otherwise fire.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import dedupe  # noqa: E402


def _hook():
    """Import the dash-named hook script as a module."""
    path = _ROOT / "scripts" / "hooks" / "on-session-start-cold-cache-clear.py"
    spec = importlib.util.spec_from_file_location("cold_cache_clear_hook", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_asking_does_not_consume_the_allowance(tmp_path):
    """THE REGRESSION. Asking must be READ-ONLY -- this is the whole bug."""
    h = _hook()
    seen = tmp_path / "cold-cache-clear-fired.txt"
    key = "cold-cache-clear@sess-1"

    assert h._fire_recorded(seen, key) is False
    # Ask a hundred times; a refused verdict asks on every reload of a long-lived session.
    for _ in range(100):
        assert h._fire_recorded(seen, key) is False
    assert not seen.exists(), "asking must never create the marker"


def test_a_recorded_fire_is_seen(tmp_path):
    """Once a fire IS recorded, the guard must hold -- the double-delivery case it exists for."""
    h = _hook()
    seen = tmp_path / "cold-cache-clear-fired.txt"
    key = "cold-cache-clear@sess-1"

    dedupe.emit_once(seen, key, "x")  # what the hook does AFTER verdict.fire
    assert h._fire_recorded(seen, key) is True
    assert h._fire_recorded(seen, "cold-cache-clear@other-session") is False


def test_an_unreadable_marker_fails_open(tmp_path):
    """A lost marker costs at most one extra clear; a spurious True kills the feature silently."""
    h = _hook()
    assert h._fire_recorded(tmp_path / "does-not-exist.txt", "k") is False
    assert h._fire_recorded(tmp_path, "k") is False  # a DIRECTORY -> OSError -> open
