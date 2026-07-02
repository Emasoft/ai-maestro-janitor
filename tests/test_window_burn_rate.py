"""Tests for the window-burn-rate alarm (TRDD-OY0W6LX5).

Real I/O, no mocks, NO network: the burn verdict is the pure `token_burn` layer, exercised
with hand-built `/api/oauth/usage` payloads; the detector is exercised only via subprocess on
its network-free early-return paths (opt-out flag off, and not-yet-due). The usage-probing
path is never hit — that is deliberately behind the rotator gather the tests bypass.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LIB = _PROJECT_ROOT / "scripts" / "lib"
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "window-burn-rate.py"

sys.path.insert(0, str(_LIB))
import token_burn as tbn  # noqa: E402

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"

# Hour-aligned synthetic NOW so window arithmetic is exact.
NOW = 1_800_000_000
_5H = 5 * 3600
_7D = 7 * 86400


def _iso(epoch: int) -> str:
    """Epoch → UTC ISO-8601 with a trailing `Z` (the shape /api/oauth/usage emits)."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None).isoformat() + "Z"


def _reset_for(window_s: int, elapsed_fraction: float) -> str:
    """The `resets_at` ISO string that puts `NOW` at `elapsed_fraction` of a `window_s`
    window (start = resets − window_s → elapsed = 1 − remaining/window_s)."""
    return _iso(NOW + int(window_s * (1.0 - elapsed_fraction)))


def _usage(*, five: tuple[float, str] | None = None, seven: tuple[float, str] | None = None) -> dict:
    """Build a usage payload from optional (utilization, resets_at) tuples per window."""
    out: dict = {}
    if five is not None:
        out["five_hour"] = {"utilization": five[0], "resets_at": five[1]}
    if seven is not None:
        out["seven_day"] = {"utilization": seven[0], "resets_at": seven[1]}
    return out


def _acct(label: str, usage: dict) -> list[dict]:
    return [{"label": label, "usage": usage}]


def test_evaluate_trips_at_1_6x() -> None:
    """7d at 46% with 2/7 of the window elapsed → 1.61× pace → one drift line naming the
    window, util, ratio and the account prefix."""
    usage = _usage(seven=(46.0, _reset_for(_7D, 2 / 7)))
    lines = tbn.evaluate(_acct("fmuaddib", usage), NOW, 1.5, 10.0)
    assert len(lines) == 1
    line = lines[0]
    assert "7d window 46%" in line and "1.6x linear pace" in line and "fmuaddib" in line


def test_evaluate_silent_at_1_2x() -> None:
    """60% at half the window elapsed → 1.2× pace → below the 1.5× bar → no alarm."""
    usage = _usage(seven=(60.0, _reset_for(_7D, 0.5)))
    assert tbn.evaluate(_acct("acct", usage), NOW, 1.5, 10.0) == []


def test_evaluate_min_util_floor_suppresses_low_use() -> None:
    """A high ratio on a barely-used window (8% util) is floored by min_util=10 → silent;
    lowering the floor to 5 lets the same window trip (proves the floor is what suppressed it)."""
    usage = _usage(seven=(8.0, _reset_for(_7D, 0.02)))  # 0.08 / 0.02 = 4.0× but util 8 < 10
    assert tbn.evaluate(_acct("acct", usage), NOW, 1.5, 10.0) == []
    assert len(tbn.evaluate(_acct("acct", usage), NOW, 1.5, 5.0)) == 1


def test_evaluate_malformed_resets_at_skipped() -> None:
    """A window whose resets_at is unparseable is dropped, never alarmed or crashed."""
    usage = {"seven_day": {"utilization": 99.0, "resets_at": "not-a-date"}}
    assert tbn.evaluate(_acct("acct", usage), NOW, 1.5, 10.0) == []


def test_account_prefix_is_local_part_only() -> None:
    """The label is the email local part only (privacy) — never the full address in a line."""
    assert tbn.account_prefix("fmuaddib@gmail.com") == "fmuaddib"
    assert tbn.account_prefix(None) == "live"
    assert tbn.account_prefix("") == "live"
    usage = _usage(seven=(46.0, _reset_for(_7D, 2 / 7)))
    line = tbn.evaluate(_acct(tbn.account_prefix("secret@example.com"), usage), NOW, 1.5, 10.0)[0]
    assert "secret" in line and "@" not in line


def test_evaluate_reports_projected_exhaustion_when_early() -> None:
    """A tripped window that will exhaust before its reset reports the projected exhaustion
    and the lead time."""
    usage = _usage(seven=(46.0, _reset_for(_7D, 2 / 7)))
    line = tbn.evaluate(_acct("acct", usage), NOW, 1.5, 10.0)[0]
    assert "projected exhaustion" in line and "before reset" in line


def test_windows_from_usage_parses_both_windows() -> None:
    """Both windows present + parseable → two computed window dicts with a real burn ratio."""
    usage = _usage(five=(80.0, _reset_for(_5H, 0.5)), seven=(46.0, _reset_for(_7D, 2 / 7)))
    wins = tbn.windows_from_usage(usage, NOW)
    assert {w["label"] for w in wins} == {"5h", "7d"}
    assert all(w["burn_ratio"] is not None for w in wins)


def _run_detector(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    for k in ("CLAUDE_PLUGIN_OPTION_WINDOW_BURN_ENABLED", "CLAUDE_PLUGIN_OPTION_WINDOW_BURN_INTERVAL"):
        full_env.pop(k, None)
    full_env.update(env)
    return subprocess.run([sys.executable, str(_DETECTOR)], env=full_env, capture_output=True, text=True, timeout=30)


def test_detector_silent_when_disabled(tmp_path: Path) -> None:
    """Opt-out flag off → exit 0, no output, and no network/rotator work (returns before the
    gather)."""
    proj = tmp_path / "proj"
    proj.mkdir()
    r = _run_detector({"CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_OPTION_WINDOW_BURN_ENABLED": "false"})
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_detector_silent_when_not_due(tmp_path: Path) -> None:
    """A fresh self-run stamp (far-future) makes the detector not-due → it returns before any
    gather (network-free) with exit 0 and no output."""
    proj = tmp_path / "proj"
    state_dir = proj / ".janitor" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "window-burn-rate.selfrun.ts").write_text("9999999999", encoding="utf-8")
    r = _run_detector({"CLAUDE_PROJECT_DIR": str(proj)})  # enabled by default
    assert r.returncode == 0
    assert r.stdout.strip() == ""
