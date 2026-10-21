"""P3c — the periodic "top up ALL your logins" proactive nudge inside
oauth-login-needed.py. TRDD-GZXTSJSR.

Real code under test (no mocks of the logic itself): `_topup_due` (pure) and
the owner-remediation record `main()` writes (the detector prints and notifies nothing; the
daemon notifies the record once per episode).
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

def _records(home: Path) -> dict[str, dict]:
    path = home / "owner-remediation.json"
    return json.loads(path.read_text(encoding="utf-8"))["conditions"] if path.is_file() else {}


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


def test_main_records_topup_on_first_run_with_no_stamp(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A healthy account (no reactive remediation due) still gets the periodic topup record on a
    fresh home — proactive, independent of any single account being currently urgent. The
    detector prints nothing and notifies nobody; the daemon notifies the record once."""
    home = tmp_path / "rotator"
    _write_healthy_slot(home, "healthy@invalid")
    _isolated_env(tmp_path, monkeypatch, home)

    rc = det.main()

    assert rc == 0
    assert capsys.readouterr().out == ""
    recs = _records(home)
    assert len(recs) == 1
    (key, rec), = recs.items()
    assert key.startswith("oauth-login-topup:") and rec["condition"] == "oauth-login-topup"
    assert "/janitor-capture-all-logins" in rec["action"]
    assert det._topup_stamp_path(home).is_file()  # stamped so the next run doesn't re-record


def test_main_does_not_rerecord_topup_within_the_cadence_window(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A second run right after the first (stamp just written) must NOT touch the record again."""
    home = tmp_path / "rotator"
    _write_healthy_slot(home, "healthy@invalid")
    _isolated_env(tmp_path, monkeypatch, home)

    base = 1_800_000_000.0
    monkeypatch.setattr(det.time, "time", lambda: base)
    assert det.main() == 0
    monkeypatch.setattr(det.time, "time", lambda: base + 3600)
    assert det.main() == 0  # same cadence window — stamp already fresh

    recs = _records(home)
    assert len(recs) == 1 and next(iter(recs.values()))["last_seen"] == int(base)


def test_main_skips_topup_when_cadence_set_to_zero(tmp_path: Path, monkeypatch, capsys) -> None:
    """Setting the cadence to 0 opts out of the periodic topup remediation entirely."""
    home = tmp_path / "rotator"
    _write_healthy_slot(home, "healthy@invalid")
    _isolated_env(tmp_path, monkeypatch, home)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS", "0")

    assert det.main() == 0

    assert _records(home) == {}


# ---------------------------------------------------------------------------
# F1 (TRDD-GZXTSJSR follow-up), reshaped by TRDD-1J9B7MWO (USER ruling 2026-10-21): the topup
# record carries its period as the episode kind (so each due cycle is a new episode for the
# daemon's once-per-episode notification), and the detector prints and notifies nothing.
# ---------------------------------------------------------------------------


def _isolated_env(tmp_path: Path, monkeypatch, home: Path) -> None:
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    for var in (
        "CLAUDE_PLUGIN_OPTION_NOTIFY_ENABLED",
        "CLAUDE_PLUGIN_OPTION_NOTIFY_WEBHOOK_URL",
        "CLAUDE_PLUGIN_OPTION_NOTIFY_MIN_SEVERITY",
        "CLAUDE_PLUGIN_OPTION_NOTIFY_MAX_PER_DAY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    monkeypatch.setenv("CLAUDE_ROTATOR_HOME", str(home))
    monkeypatch.setenv("CLAUDE_ROTATOR_PROFILES", str(tmp_path / "profiles"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "proj"))
    monkeypatch.setenv("HOME", str(tmp_path / "userhome"))
    (tmp_path / "proj").mkdir(exist_ok=True)
    (tmp_path / "userhome").mkdir(exist_ok=True)


def test_main_topup_is_a_new_episode_next_due_cycle(tmp_path: Path, monkeypatch) -> None:
    """A second due fire 4 days later (3-day cadence) records under a NEW key (the period is the record's
    kind), so the daemon's episode logic notifies again instead of staying silent behind last
    cycle's episode."""
    home = tmp_path / "rotator"
    _write_healthy_slot(home, "healthy@invalid")
    _isolated_env(tmp_path, monkeypatch, home)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS", "3")

    base = 1_800_000_000.0
    monkeypatch.setattr(det.time, "time", lambda: base)
    assert det.main() == 0
    assert float(det._topup_stamp_path(home).read_text(encoding="utf-8")) == base

    later = base + 4 * 86400  # past the 3-day cadence set below, inside the 7-day record retention
    monkeypatch.setattr(det.time, "time", lambda: later)
    assert det.main() == 0
    assert float(det._topup_stamp_path(home).read_text(encoding="utf-8")) == later
    recs = _records(home)
    assert len(recs) == 2 and {r["kind"] for r in recs.values()} == {
        time.strftime("%Y-%m-%d", time.localtime(base)), time.strftime("%Y-%m-%d", time.localtime(later))}


