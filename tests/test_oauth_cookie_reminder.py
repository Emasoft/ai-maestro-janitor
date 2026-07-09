"""Tests for the opt-in oauth-cookie-reminder detector.

Builds an isolated temp rotator home (state.json + slot files) and per-account
Chrome profiles (a minimal Cookies sqlite carrying a `sessionKey` at a chosen
expiry), runs the detector as a subprocess with a hermetic env, and asserts the
emit/silent behaviour. Read-only detector; no network, no real keychain.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_DETECTOR = _HERE.parent / "scripts" / "detectors" / "oauth-cookie-reminder.py"
_EPOCH_OFFSET = 11644473600  # seconds between 1601-01-01 and 1970-01-01


def _load_detector():
    """Import the hyphenated detector module by path (for in-process monkeypatching).

    scripts/oauth_rotator must be on sys.path first so the detector's
    `import supervisor` resolves (the detector adds it itself, but importing by
    spec runs that top-level code, so the path has to exist when exec'd)."""
    sys.path.insert(0, str(_HERE.parent / "scripts" / "lib"))
    sys.path.insert(0, str(_HERE.parent / "scripts" / "oauth_rotator"))
    spec = importlib.util.spec_from_file_location("oauth_cookie_reminder_under_test", _DETECTOR)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_cookies(profile_dir: Path, session_expiry_days: float | None) -> None:
    """Write a Chrome-like Cookies sqlite with a sessionKey for claude.ai.

    session_expiry_days is None → create NO Cookies file (profile never logged in).
    """
    if session_expiry_days is None:
        return
    default = profile_dir / "Default"
    default.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(default / "Cookies")
    con.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, expires_utc INTEGER)")
    exp = int((time.time() + session_expiry_days * 86400 + _EPOCH_OFFSET) * 1_000_000)
    con.execute("INSERT INTO cookies VALUES (?, ?, ?)", ("claude.ai", "sessionKey", exp))
    con.commit()
    con.close()


def _run(
    tmp_path: Path,
    slots: dict[str, bool | float],
    profiles: dict[str, float | None],
    *,
    env_extra: dict[str, str] | None = None,
) -> tuple[str, int]:
    """slots value: True = refresh-capable; False = no-refresh setup-token (365d);
    a float = no-refresh setup-token expiring in that many days."""
    home = tmp_path / "rotator"
    (home / "slots").mkdir(parents=True, exist_ok=True)
    (home / "state.json").write_text(json.dumps({"slots": {e: {} for e in slots}}))
    # The detector now gates its keychain reads on the rotator opt-in (TRDD-K3WQ7XM9): a
    # "paused" rotator must never touch the keychain from the heartbeat. These integration
    # tests exercise the opted-in path, so mark the home opted-in.
    (home / "opt-in.flag").touch()
    for email, spec in slots.items():
        oauth: dict[str, object] = {"accessToken": "x"}
        if spec is True:
            oauth["refreshToken"] = "r"
            oauth["expiresAt"] = int((time.time() + 8 * 3600) * 1000)
        else:
            days = 365.0 if spec is False else float(spec)
            oauth["expiresAt"] = int((time.time() + days * 86400) * 1000)
        (home / "slots" / f"{email}.json").write_text(json.dumps({"claudeAiOauth": oauth}))

    prof_root = tmp_path / "profiles"
    for email, cookie_days in profiles.items():
        _make_cookies(prof_root / f"chrome-profile-{email}", cookie_days)

    env = dict(os.environ)
    env.pop("CLAUDE_PLUGIN_DATA", None)  # hermetic: don't let a real data dir leak in
    env.update(
        {
            "CLAUDE_ROTATOR_HOME": str(home),
            "CLAUDE_ROTATOR_PROFILES": str(prof_root),
            "CLAUDE_PROJECT_DIR": str(tmp_path / "proj"),
            "HOME": str(tmp_path / "home"),
        }
    )
    if env_extra:
        env.update(env_extra)
    (tmp_path / "proj").mkdir(exist_ok=True)
    (tmp_path / "home").mkdir(exist_ok=True)
    r = subprocess.run(
        [sys.executable, str(_DETECTOR), "--one-shot"],
        capture_output=True,
        text=True,
        env=env,
    )
    return r.stdout, r.returncode


def test_silent_when_cookies_healthy(tmp_path: Path) -> None:
    """Cookie 28d (> 7d default) + healthy OAuth → no reminder."""
    out, rc = _run(tmp_path, {"a@x.com": True}, {"a@x.com": 28.0})
    assert rc == 0
    assert "oauth-cookie-refresh" not in out


def test_reminds_when_cookie_near_expiry(tmp_path: Path) -> None:
    """Cookie 3d (< 7d) + healthy OAuth → reminder with safe-window note."""
    out, rc = _run(tmp_path, {"a@x.com": True}, {"a@x.com": 3.0})
    assert rc == 0
    assert "[oauth-cookie-refresh]" in out
    assert "a@x.com" in out
    assert "safe window" in out


def test_reminds_when_no_session(tmp_path: Path) -> None:
    """No Cookies file at all → 'login needed' reminder."""
    out, _ = _run(tmp_path, {"a@x.com": True}, {"a@x.com": None})
    assert "[oauth-cookie-refresh]" in out
    assert "login needed" in out


def test_setup_token_near_expiry_reminds(tmp_path: Path) -> None:
    """Cookie healthy (28d) but a no-refresh setup-token expiring in 10d (< 30d)
    → RE-CAPTURE reminder, even though the cookie itself is fine."""
    out, _ = _run(
        tmp_path,
        {"s@x.com": 10.0},  # no-refresh setup-token, 10d to expiry
        {"s@x.com": 28.0},
        env_extra={"CLAUDE_ROTATOR_SETUP_REMIND_DAYS": "30"},
    )
    assert "[oauth-cookie-refresh]" in out
    assert "setup-token" in out


def test_keychain_backed_refresh_slot_is_seen_healthy_no_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P2 (audit §3.2): the detector reads slot OAuth facts KEYCHAIN-FIRST via
    supervisor._slot_facts, NOT the deleted plaintext slots/<email>.json. A
    refresh-capable slot that lives ONLY in the keychain (no plaintext file on disk)
    must classify as healthy → the near-expiry cookie reminder carries the SAFE-window
    tail, never the URGENT 'no account has healthy OAuth' tail."""
    mod = _load_detector()
    home = tmp_path / "rotator"
    (home / "slots").mkdir(parents=True, exist_ok=True)
    (home / "state.json").write_text(json.dumps({"slots": {"a@x.com": {}}}))
    # NO plaintext slot file — the slot lives only in the (faked) keychain.
    assert not (home / "slots" / "a@x.com.json").exists()
    prof_root = tmp_path / "profiles"
    _make_cookies(prof_root / "chrome-profile-a@x.com", 3.0)  # cookie near expiry → reminder fires

    # The keychain-aware reader the detector now delegates to. Returns a
    # refresh-capable slot for a@x.com — the exact thing the old plaintext reader
    # could never see (the files were deleted post-migration).
    fact = mod.supervisor.SlotFact(email="a@x.com", has_refresh=True, expires_days=None)
    monkeypatch.setattr(mod.supervisor, "_slot_facts", lambda _home, _now: (fact,))

    monkeypatch.setenv("CLAUDE_ROTATOR_HOME", str(home))
    monkeypatch.setenv("CLAUDE_ROTATOR_PROFILES", str(prof_root))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "proj"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    (tmp_path / "proj").mkdir(exist_ok=True)
    (tmp_path / "home").mkdir(exist_ok=True)

    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    rc = mod.main()
    out = buf.getvalue()
    assert rc == 0
    assert "[oauth-cookie-refresh]" in out          # cookie 3d < 7d → reminder fired
    assert "a@x.com" in out
    assert "safe window" in out                      # healthy OAuth seen via the keychain reader
    assert "no account has healthy OAuth" not in out  # NOT the urgent/unhealthy tail


def test_oauth_map_delegates_to_slot_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_oauth_map is a thin adapter over supervisor._slot_facts (single keychain-aware
    source of truth) — it forwards (has_refresh, expires_days) per email verbatim."""
    mod = _load_detector()
    home = tmp_path / "rotator"
    home.mkdir()
    now = 1_780_000_000.0
    facts = (
        mod.supervisor.SlotFact(email="full@x.com", has_refresh=True, expires_days=2.0),
        mod.supervisor.SlotFact(email="setup@x.com", has_refresh=False, expires_days=5.0),
    )
    monkeypatch.setattr(mod.supervisor, "_slot_facts", lambda _home, _now: facts)
    got = mod._oauth_map(home, now)
    assert got == {"full@x.com": (True, 2.0), "setup@x.com": (False, 5.0)}


def test_opt_in_noop_without_rotator(tmp_path: Path) -> None:
    """No rotator home with a state.json anywhere → silent no-op."""
    env = dict(os.environ)
    env.pop("CLAUDE_PLUGIN_DATA", None)
    env.update(
        {
            "CLAUDE_ROTATOR_HOME": str(tmp_path / "nope"),
            "CLAUDE_PROJECT_DIR": str(tmp_path / "proj"),
            "HOME": str(tmp_path / "home"),
        }
    )
    (tmp_path / "proj").mkdir()
    (tmp_path / "home").mkdir()
    r = subprocess.run(
        [sys.executable, str(_DETECTOR), "--one-shot"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == ""
