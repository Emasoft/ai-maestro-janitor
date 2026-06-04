"""Tests for the post-login auto-bootstrap in rotator.py (Part B, TRDD-32acd15f).

`_bootstrap_seeded_slots()` mints a refresh-bearing slot for every account that
was SEEDED by a human login (a live claude.ai Chrome session) but cannot yet
self-renew (no refreshToken). It does so by invoking slot_capture_browser.py as
a TIMED subprocess.

All real, NO mocks of the code under test:
  * `_bootstrap_eligible` is a pure fn, called directly.
  * `_bootstrap_seeded_slots`: real tmp state.json + real fake Chrome Cookies
    sqlite files drive the session-key check; `read_slot` returns hand-built
    blobs; ONLY the external `slot_capture_browser` invocation is monkeypatched
    to a recorder — so NO browser launches, NO network, NO keychain is touched.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import time
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ROTATOR_PY = _HERE.parent / "scripts" / "oauth_rotator" / "rotator.py"
_EPOCH_OFFSET = 11644473600  # seconds between 1601-01-01 and 1970-01-01


def _load_rotator():
    """Import rotator.py by path (it lives outside any package)."""
    spec = importlib.util.spec_from_file_location("rotator_bootstrap_under_test", _ROTATOR_PY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rotator = _load_rotator()


def _blob(token: str, *, refresh: str | None) -> dict:
    inner: dict = {"accessToken": token}
    if refresh is not None:
        inner["refreshToken"] = refresh
    return {"claudeAiOauth": inner}


def _make_session(profiles_root: Path, email: str, expiry_days: float | None) -> None:
    """Write a fake Chrome Cookies sqlite for `chrome-profile-<email>`.

    expiry_days None → no Cookies file (no seeded session). Negative → expired.
    """
    if expiry_days is None:
        return
    default = profiles_root / f"chrome-profile-{email}" / "Default"
    default.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(default / "Cookies")
    con.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, expires_utc INTEGER)")
    exp = int((time.time() + expiry_days * 86400 + _EPOCH_OFFSET) * 1_000_000)
    con.execute("INSERT INTO cookies VALUES (?, ?, ?)", ("claude.ai", "sessionKey", exp))
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# PURE eligibility truth table.
# ---------------------------------------------------------------------------
def test_bootstrap_eligible_only_no_refresh_with_session() -> None:
    """Eligible iff it CANNOT self-renew (no refresh) AND HAS a live session to mint from."""
    assert rotator._bootstrap_eligible(False, True) is True
    assert rotator._bootstrap_eligible(False, False) is False  # nothing to mint from
    assert rotator._bootstrap_eligible(True, True) is False    # already self-renews
    assert rotator._bootstrap_eligible(True, False) is False


# ---------------------------------------------------------------------------
# _bootstrap_seeded_slots integration — only the browser subprocess is faked.
# ---------------------------------------------------------------------------
def _wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    slots: dict[str, dict],
) -> list[str]:
    """slots maps email -> {"refresh": str|None, "session": float|None}. Builds
    tmp state.json + fake Cookies, faked read_slot, and a recording stand-in for
    the slot_capture_browser invocation. Returns the recorder list of bootstrapped
    emails the fake "captured"."""
    root = tmp_path / "root"
    (root / "slots").mkdir(parents=True, exist_ok=True)
    profiles = root / "profiles"
    monkeypatch.setattr(rotator, "ROOT", root)
    monkeypatch.setattr(rotator, "SLOTS", root / "slots")
    monkeypatch.setattr(rotator, "STATE_FILE", root / "state.json")
    rotator.save_state({"live_email": None, "live_fp": None,
                        "slots": {e: {} for e in slots}})

    blobs = {e: _blob(e.split("@", 1)[0].upper(), refresh=spec["refresh"])
             for e, spec in slots.items()}
    monkeypatch.setattr(rotator, "read_slot", lambda e: blobs.get(e))
    for email, spec in slots.items():
        _make_session(profiles, email, spec["session"])

    captured: list[str] = []
    # The ONLY external dependency we stub: the browser subprocess. A real call
    # would launch Playwright Chrome + hit the OAuth endpoint — forbidden in tests.
    monkeypatch.setattr(rotator, "_invoke_slot_capture",
                        lambda email: captured.append(email) or True)
    return captured


def test_bootstraps_only_seeded_no_refresh_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Three slots: no-refresh+session (bootstrap), no-refresh+no-session (skip — nothing
    to mint from), has-refresh+session (skip — already self-renews). Only the first is captured."""
    captured = _wire(
        tmp_path,
        monkeypatch,
        {
            "seeded@x.com": {"refresh": None, "session": 20.0},
            "orphan@x.com": {"refresh": None, "session": None},
            "healthy@x.com": {"refresh": "r", "session": 20.0},
        },
    )
    done = rotator._bootstrap_seeded_slots()
    assert captured == ["seeded@x.com"]
    assert done == ["seeded@x.com"]


def test_expired_session_is_not_bootstrappable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An EXPIRED claude.ai session has no live sessionKey to mint a refresh from → skip."""
    captured = _wire(
        tmp_path,
        monkeypatch,
        {"stale@x.com": {"refresh": None, "session": -3.0}},
    )
    done = rotator._bootstrap_seeded_slots()
    assert captured == []
    assert done == []


def test_no_eligible_slots_invokes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All slots self-renew → the browser subprocess is never invoked."""
    captured = _wire(
        tmp_path,
        monkeypatch,
        {
            "a@x.com": {"refresh": "r", "session": 20.0},
            "b@x.com": {"refresh": "r", "session": None},
        },
    )
    done = rotator._bootstrap_seeded_slots()
    assert captured == []
    assert done == []


def test_bootstrap_never_raises_on_capture_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing/raising capture is best-effort: it is logged + skipped, never propagated,
    and a LATER eligible slot is still attempted."""
    root = tmp_path / "root"
    (root / "slots").mkdir(parents=True, exist_ok=True)
    profiles = root / "profiles"
    monkeypatch.setattr(rotator, "ROOT", root)
    monkeypatch.setattr(rotator, "SLOTS", root / "slots")
    monkeypatch.setattr(rotator, "STATE_FILE", root / "state.json")
    emails = ["boom@x.com", "ok@x.com"]
    rotator.save_state({"live_email": None, "live_fp": None, "slots": {e: {} for e in emails}})
    blobs = {e: _blob(e.split("@", 1)[0].upper(), refresh=None) for e in emails}
    monkeypatch.setattr(rotator, "read_slot", lambda e: blobs.get(e))
    for e in emails:
        _make_session(profiles, e, 20.0)

    attempted: list[str] = []

    def _capture(email: str) -> bool:
        attempted.append(email)
        if email == "boom@x.com":
            raise RuntimeError("playwright blew up")
        return True

    monkeypatch.setattr(rotator, "_invoke_slot_capture", _capture)
    done = rotator._bootstrap_seeded_slots()  # must NOT raise
    assert set(attempted) == {"boom@x.com", "ok@x.com"}  # the failure didn't abort the loop
    assert done == ["ok@x.com"]                          # only the successful one counts


def test_bootstrap_uses_profiles_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The profiles root honours CLAUDE_ROTATOR_PROFILES (mirrors open-login.sh /
    slot_capture_browser), not just <ROOT>/profiles."""
    root = tmp_path / "root"
    (root / "slots").mkdir(parents=True, exist_ok=True)
    alt_profiles = tmp_path / "elsewhere" / "profiles"
    monkeypatch.setattr(rotator, "ROOT", root)
    monkeypatch.setattr(rotator, "SLOTS", root / "slots")
    monkeypatch.setattr(rotator, "STATE_FILE", root / "state.json")
    monkeypatch.setenv("CLAUDE_ROTATOR_PROFILES", str(alt_profiles))
    rotator.save_state({"live_email": None, "live_fp": None, "slots": {"e@x.com": {}}})
    monkeypatch.setattr(rotator, "read_slot", lambda _: _blob("E", refresh=None))
    _make_session(alt_profiles, "e@x.com", 20.0)  # session lives under the OVERRIDE root
    captured: list[str] = []
    monkeypatch.setattr(rotator, "_invoke_slot_capture",
                        lambda email: captured.append(email) or True)
    done = rotator._bootstrap_seeded_slots()
    assert captured == ["e@x.com"]
    assert done == ["e@x.com"]
