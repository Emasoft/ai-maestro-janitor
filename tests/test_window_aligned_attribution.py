"""Window-ALIGNED attribution (TRDD-0NRVNDSZ).

The subscription meter bills FIXED windows ending at `resets_at`, so attribution must sum
`[resets_at − window_s, now]` — not the trailing `[now − window_s, now]` the first version
used (the user caught the mismatch on 2026-07-02: their 5h window ran 14:40→19:40 while the
report summed a sliding 5h). These tests pin the aligned bounds end to end: the pure
`window_starts` derivation, the `project_metrics` override, and the cache's bounds-mismatch
staleness rule.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import token_burn as tb  # noqa: E402
import token_history as th  # noqa: E402

NOW = 1_800_000_000


def _iso(epoch: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _usage(reset_5h: int, reset_7d: int) -> dict:
    return {
        "five_hour": {"utilization": 50, "resets_at": _iso(reset_5h)},
        "seven_day": {"utilization": 30, "resets_at": _iso(reset_7d)},
    }


def test_window_starts_derives_resets_minus_window() -> None:
    """5h/7d starts are resets_at − window_s, from the live account's payload."""
    accounts = [{"label": "live", "usage": _usage(NOW + 3600, NOW + 86400)}]
    w5_lo, w7_lo = tb.window_starts(accounts, NOW)
    assert w5_lo == NOW + 3600 - 5 * 3600
    assert w7_lo == NOW + 86400 - 7 * 86400


def test_window_starts_prefers_live_and_survives_junk() -> None:
    """The live account's windows win over a slot's; junk entries never raise."""
    accounts = [
        "junk",
        {"label": "slot-a", "usage": _usage(NOW + 999, NOW + 999)},
        {"label": "live", "usage": _usage(NOW + 3600, NOW + 86400)},
    ]
    w5_lo, _ = tb.window_starts(accounts, NOW)
    assert w5_lo == NOW + 3600 - 5 * 3600


def test_window_starts_empty_or_malformed_is_none_none() -> None:
    """No parseable window → (None, None) so callers fall back to trailing."""
    assert tb.window_starts([], NOW) == (None, None)
    assert tb.window_starts([{"label": "live", "usage": {"five_hour": {}}}], NOW) == (None, None)


def _event(ts: int, output: int = 100) -> th.Event:
    return th.Event(ts=ts, weighted=float(output), output=output, cache_creation=0, tool_calls=0, subagent_spawns=0)


def test_project_metrics_aligned_bounds_override_trailing() -> None:
    """An event OUTSIDE the aligned 5h window but INSIDE the trailing one is excluded."""
    w5_lo = NOW - 2 * 3600  # aligned window opened 2h ago (reset in 3h)
    ev_in = _event(NOW - 3600)
    ev_out = _event(NOW - 3 * 3600)  # 3h ago: inside trailing-5h, OUTSIDE the aligned window
    trailing = th.project_metrics([ev_in, ev_out], NOW)
    aligned = th.project_metrics([ev_in, ev_out], NOW, w5_lo=w5_lo)
    assert trailing["roll_5h"] == 200.0
    assert aligned["roll_5h"] == 100.0


def test_cache_bounds_mismatch_is_stale(tmp_path: Path, monkeypatch) -> None:
    """A cached fleet computed with different bounds is NOT reused."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    import token_attribution_cache as tac

    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    fleet = tac.get(projects_root, NOW, w5_lo=111, w7_lo=222)
    assert fleet["w5_lo"] == 111
    # Same bounds → served from cache (identical dict round-trips).
    assert tac.load_fresh(NOW, w5_lo=111, w7_lo=222) is not None
    # Different / absent bounds → stale, must recompute.
    assert tac.load_fresh(NOW, w5_lo=333, w7_lo=222) is None
    assert tac.load_fresh(NOW) is None
