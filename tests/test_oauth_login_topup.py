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


def test_topup_cycle_is_the_calendar_period_number() -> None:
    """Same period -> same cycle (one episode); the next period -> the next cycle (a new episode)."""
    period = 7 * 86400
    base = 1_800_000_000.0
    cycle = det._topup_cycle(base, 7.0)
    assert det._topup_cycle(base + 3600, 7.0) in (cycle, cycle + 1)  # only a period edge may differ
    assert det._topup_cycle(cycle * period, 7.0) == cycle
    assert det._topup_cycle(cycle * period + period - 1, 7.0) == cycle
    assert det._topup_cycle((cycle + 1) * period, 7.0) == cycle + 1


def test_topup_days_default_is_seven(monkeypatch) -> None:
    """Default cadence is 7 days when CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS is unset."""
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS", raising=False)
    assert det._topup_days() == 7.0


def test_topup_days_env_override(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS", "14")
    assert det._topup_days() == 14.0


def test_main_records_topup_on_first_run(tmp_path: Path, monkeypatch, capsys) -> None:
    """A healthy account (no reactive remediation due) still gets the periodic topup record on a
    fresh home - proactive, independent of any single account being currently urgent. The
    detector prints nothing and notifies nobody; the daemon notifies the record once. No
    "last nudged" stamp is written (it was written before the daemon notified and lost the
    nudge whenever the daemon was down)."""
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
    assert not (home / ".login-topup-last.txt").exists()


def test_main_refreshes_the_topup_record_every_heartbeat_of_the_cycle(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A second run in the same cycle keeps ONE record under the SAME key (same episode, the
    daemon notifies once) and refreshes last_seen, so a daemon that was down at the first
    heartbeat still sees a fresh record to notify."""
    home = tmp_path / "rotator"
    _write_healthy_slot(home, "healthy@invalid")
    _isolated_env(tmp_path, monkeypatch, home)

    base = 1_800_000_000.0
    monkeypatch.setattr(det.time, "time", lambda: base)
    assert det.main() == 0
    first = _records(home)
    monkeypatch.setattr(det.time, "time", lambda: base + 60)
    assert det.main() == 0

    recs = _records(home)
    assert set(recs) == set(first)
    assert next(iter(recs.values()))["last_seen"] == int(base) + 60


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


def test_main_topup_is_a_new_episode_next_cycle(tmp_path: Path, monkeypatch) -> None:
    """A heartbeat 4 days later (3-day cycle) records under a NEW key (the cycle number is the
    record kind), so the daemon notifies again; the previous cycle's record is superseded
    (one record per condition)."""
    home = tmp_path / "rotator"
    _write_healthy_slot(home, "healthy@invalid")
    _isolated_env(tmp_path, monkeypatch, home)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS", "3")

    base = 1_800_000_000.0
    monkeypatch.setattr(det.time, "time", lambda: base)
    assert det.main() == 0
    (rec1,) = _records(home).values()

    later = base + 4 * 86400
    monkeypatch.setattr(det.time, "time", lambda: later)
    assert det.main() == 0
    (rec2,) = _records(home).values()
    assert rec1["kind"] != rec2["kind"]
    assert rec2["kind"] == str(det._topup_cycle(later, 3.0))


