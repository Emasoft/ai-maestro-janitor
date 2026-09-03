"""P3c — the periodic "top up ALL your logins" proactive nudge inside
oauth-login-needed.py. TRDD-GZXTSJSR.

Real code under test (no mocks of the logic itself): `_topup_due` (pure) and
the notify.push firing from `main()` (monkeypatch only the notify boundary,
same pattern as test_oauth_login_needed.py).
"""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DETECTOR = _HERE.parent / "scripts" / "detectors" / "oauth-login-needed.py"


def _load_detector():
    spec = importlib.util.spec_from_file_location("oauth_login_topup_under_test", _DETECTOR)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


det = _load_detector()


def _write_healthy_slot(home: Path, email: str) -> None:
    """One account that does NOT need a login nudge (healthy refresh token far from
    expiry) — isolates the topup nudge from the reactive one for these tests."""
    (home / "slots").mkdir(parents=True, exist_ok=True)
    (home / "state.json").write_text(json.dumps({"slots": {email: {"refresh_failures": 0}}}))
    (home / "opt-in.flag").touch()
    oauth = {
        "accessToken": "x",
        "refreshToken": "r",
        "expiresAt": int((time.time() + 30 * 86400) * 1000),
    }
    (home / "slots" / f"{email}.json").write_text(json.dumps({"claudeAiOauth": oauth}))


def test_topup_due_true_when_no_stamp_exists(tmp_path: Path) -> None:
    """No stamp yet -> due (fail-open toward nudging, never toward silence)."""
    assert det._topup_due(tmp_path, time.time(), 7.0) is True


def test_topup_due_false_within_the_cadence_window(tmp_path: Path) -> None:
    """A stamp written 1 day ago, cadence 7 days -> not due yet."""
    now = time.time()
    det._topup_stamp_path(tmp_path).write_text(str(now - 1 * 86400))
    assert det._topup_due(tmp_path, now, 7.0) is False


def test_topup_due_true_once_the_cadence_window_elapses(tmp_path: Path) -> None:
    """A stamp written 8 days ago, cadence 7 days -> due again."""
    now = time.time()
    det._topup_stamp_path(tmp_path).write_text(str(now - 8 * 86400))
    assert det._topup_due(tmp_path, now, 7.0) is True


def test_topup_due_true_on_a_corrupt_stamp(tmp_path: Path) -> None:
    """A corrupt/unparseable stamp reads as due — fail-open, not permanently silenced."""
    det._topup_stamp_path(tmp_path).write_text("not-a-number")
    assert det._topup_due(tmp_path, time.time(), 7.0) is True


def test_topup_days_default_is_seven(monkeypatch) -> None:
    """Default cadence is 7 days when CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS is unset."""
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS", raising=False)
    assert det._topup_days() == 7.0


def test_topup_days_env_override(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS", "14")
    assert det._topup_days() == 14.0


def test_main_fires_topup_notify_on_first_run_with_no_stamp(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A healthy account (no reactive nudge due) still gets the periodic topup push on a
    fresh home — proactive, independent of any single account being currently urgent."""
    calls = []
    monkeypatch.setattr(det.notify, "push", lambda **kw: calls.append(kw) or "pushed")
    home = tmp_path / "rotator"
    _write_healthy_slot(home, "healthy@x.com")
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    monkeypatch.setenv("CLAUDE_ROTATOR_HOME", str(home))
    monkeypatch.setenv("CLAUDE_ROTATOR_PROFILES", str(tmp_path / "profiles"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "proj"))
    monkeypatch.setenv("HOME", str(tmp_path / "userhome"))
    (tmp_path / "proj").mkdir(exist_ok=True)
    (tmp_path / "userhome").mkdir(exist_ok=True)

    rc = det.main()

    assert rc == 0
    topup_calls = [c for c in calls if c["code"] == "OAUTH-LOGIN-TOPUP"]
    assert len(topup_calls) == 1
    assert topup_calls[0]["sev"] == "HIGH"
    assert topup_calls[0]["hint"] == "/janitor-capture-all-logins"
    assert det._topup_stamp_path(home).is_file()  # stamped so the next run doesn't re-fire


def test_main_does_not_refire_topup_within_the_cadence_window(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A second run right after the first (stamp just written) must NOT re-push."""
    calls = []
    monkeypatch.setattr(det.notify, "push", lambda **kw: calls.append(kw) or "pushed")
    home = tmp_path / "rotator"
    _write_healthy_slot(home, "healthy@x.com")
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    monkeypatch.setenv("CLAUDE_ROTATOR_HOME", str(home))
    monkeypatch.setenv("CLAUDE_ROTATOR_PROFILES", str(tmp_path / "profiles"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "proj"))
    monkeypatch.setenv("HOME", str(tmp_path / "userhome"))
    (tmp_path / "proj").mkdir(exist_ok=True)
    (tmp_path / "userhome").mkdir(exist_ok=True)

    assert det.main() == 0
    assert det.main() == 0  # second run, same tick — stamp already fresh

    topup_calls = [c for c in calls if c["code"] == "OAUTH-LOGIN-TOPUP"]
    assert len(topup_calls) == 1


def test_main_skips_topup_when_cadence_set_to_zero(tmp_path: Path, monkeypatch, capsys) -> None:
    """Setting the cadence to 0 opts out of the periodic topup nudge entirely."""
    calls = []
    monkeypatch.setattr(det.notify, "push", lambda **kw: calls.append(kw) or "pushed")
    home = tmp_path / "rotator"
    _write_healthy_slot(home, "healthy@x.com")
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    monkeypatch.setenv("CLAUDE_ROTATOR_HOME", str(home))
    monkeypatch.setenv("CLAUDE_ROTATOR_PROFILES", str(tmp_path / "profiles"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "proj"))
    monkeypatch.setenv("HOME", str(tmp_path / "userhome"))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS", "0")
    (tmp_path / "proj").mkdir(exist_ok=True)
    (tmp_path / "userhome").mkdir(exist_ok=True)

    assert det.main() == 0

    topup_calls = [c for c in calls if c["code"] == "OAUTH-LOGIN-TOPUP"]
    assert topup_calls == []
