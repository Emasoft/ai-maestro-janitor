"""GH#297 / TRDD-3GF9PSQB: `identify_environment.py`'s "marketplace refreshed <age>"
line read only the last-run stamp, which `daemon.py::Task.run` / `poll_background`
write unconditionally on failure too — so a marketplace-refresh task failing every
run displayed as freshly healthy. This is one of the two readers the issue named
(the other is `fleet_status.py`, covered by
test_fleet_status_chore_stamp_failure.py); the fix consults
`global_state.read_failcount` beside the stamp, same as `daemon_watchdog.py`
already does for its own drift alarm.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "identify_environment.py"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


def _load():
    spec = importlib.util.spec_from_file_location("identify_environment_under_test", str(_SCRIPT))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _info_with_marketplace(mod, *, fails: int):
    info = mod.gather()
    jan = info.setdefault("plugins_env", {}).setdefault("janitor", {})
    jan["marketplace_refresh_ts"] = 1_700_000_000
    jan["marketplace_refresh_fails"] = fails
    return info


def test_marketplace_refresh_quarantined_past_threshold_is_flagged():
    mod = _load()
    out = mod._render(_info_with_marketplace(mod, fails=mod.global_state.QUARANTINE_AFTER_FAILS))
    assert "marketplace QUARANTINED" in out
    assert f"{mod.global_state.QUARANTINE_AFTER_FAILS}x consecutive" in out


def test_marketplace_refresh_single_failure_below_quarantine_is_still_flagged():
    # Coordinator-review follow-up (GH#297): gating "healthy" on
    # QUARANTINE_AFTER_FAILS (3) left kill #1 and kill #2 showing a bare fresh
    # age — the issue's exact complaint. A test that only passes at the
    # threshold would not catch a regression back to that gate.
    mod = _load()
    out = mod._render(_info_with_marketplace(mod, fails=1))
    assert "marketplace FAILING" in out
    assert "1x consecutive" in out
    assert "marketplace QUARANTINED" not in out


def test_marketplace_refresh_healthy_reads_as_before():
    mod = _load()
    out = mod._render(_info_with_marketplace(mod, fails=0))
    assert "marketplace FAILING" not in out
    assert "marketplace refreshed" in out
