"""Tests for the opt-in oauth-login-needed detector.

Two layers, both real (no mocks of the code under test):

  * PURE classifier (`slot_needs_login`) truth table — imported by path and
    called directly. Decides whether an account needs a ONE-TIME human login
    because it can neither self-renew (no refreshToken) nor auto-bootstrap (no
    live Chrome session to mint a refresh from).
  * Integration — build an isolated temp rotator home (state.json + plaintext
    slot files) and per-account Chrome profiles (a minimal Cookies sqlite
    carrying a `sessionKey` at a chosen expiry), run the detector as a
    subprocess with a hermetic env, and assert which emails are surfaced + the
    daily dedupe. Read-only detector; no network, no real keychain write, no
    browser.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DETECTOR = _HERE.parent / "scripts" / "detectors" / "oauth-login-needed.py"
_EPOCH_OFFSET = 11644473600  # seconds between 1601-01-01 and 1970-01-01


def _load_detector():
    """Import the hyphenated detector by path (it lives outside any package)."""
    spec = importlib.util.spec_from_file_location("oauth_login_needed_under_test", _DETECTOR)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


det = _load_detector()


# ---------------------------------------------------------------------------
# PURE classifier truth table — the whole decision in one unit-testable fn.
# ---------------------------------------------------------------------------
def test_needs_login_no_refresh_expired_no_session() -> None:
    """No refresh + token expired/None + no seeded session → needs a human login."""
    assert det.slot_needs_login(False, None, False, 1.0) is True
    assert det.slot_needs_login(False, -3.0, False, 1.0) is True
    assert det.slot_needs_login(False, 0.5, False, 1.0) is True  # within grace


def test_has_refresh_never_needs_login() -> None:
    """A refresh-capable slot is keepalive-refreshed by the daemon → never nudged."""
    assert det.slot_needs_login(True, None, False, 1.0) is False
    assert det.slot_needs_login(True, -5.0, False, 1.0) is False
    assert det.slot_needs_login(True, -5.0, True, 1.0) is False


def test_has_session_is_bootstrap_case_not_login() -> None:
    """No refresh but a live Chrome session → bootstrap-eligible (Part B), NOT a login nudge."""
    assert det.slot_needs_login(False, None, True, 1.0) is False
    assert det.slot_needs_login(False, -10.0, True, 1.0) is False


def test_capture_stalled_truth_table() -> None:
    """B3: slot_capture_stalled is True iff logged-in (has session) but no refreshToken yet —
    the 'capture launched but never completed' case. has_refresh OR no-session → not stalled."""
    assert det.slot_capture_stalled(False, True) is True     # logged in, capture not done
    assert det.slot_capture_stalled(True, True) is False      # already self-renews
    assert det.slot_capture_stalled(False, False) is False    # no session → that's a LOGIN nudge
    assert det.slot_capture_stalled(True, False) is False


def test_no_refresh_token_has_runway_no_login() -> None:
    """No refresh, no session, but the setup-token still has runway (> grace) → no nudge yet."""
    assert det.slot_needs_login(False, 10.0, False, 1.0) is False
    assert det.slot_needs_login(False, 1.0001, False, 1.0) is False  # just past grace


def test_no_refresh_none_days_no_session_needs_login() -> None:
    """No refresh, no session, and an undatable/missing token → treat as needing a login."""
    assert det.slot_needs_login(False, None, False, 1.0) is True


def test_grace_boundary_is_inclusive() -> None:
    """token_days exactly == grace is at/within grace → needs login (<= grace)."""
    assert det.slot_needs_login(False, 1.0, False, 1.0) is True
    assert det.slot_needs_login(False, 2.0, False, 2.0) is True


# ---------------------------------------------------------------------------
# Integration — subprocess with a hermetic env, fake Chrome Cookies + slots.
# ---------------------------------------------------------------------------
def _make_cookies(profile_dir: Path, session_expiry_days: float | None) -> None:
    """Write a Chrome-like Cookies sqlite with a sessionKey for claude.ai.

    session_expiry_days is None → create NO Cookies file (profile never logged
    in / no live session). A negative value writes an already-EXPIRED session.
    """
    if session_expiry_days is None:
        return
    default = profile_dir / "Default"
    default.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(default / "Cookies")
    # IF NOT EXISTS so the helper is idempotent — a second _run against the same tmp_path
    # (the daily-dedupe tests) must not crash on an already-created Cookies db.
    con.execute("CREATE TABLE IF NOT EXISTS cookies (host_key TEXT, name TEXT, expires_utc INTEGER)")
    exp = int((time.time() + session_expiry_days * 86400 + _EPOCH_OFFSET) * 1_000_000)
    con.execute("INSERT INTO cookies VALUES (?, ?, ?)", ("claude.ai", "sessionKey", exp))
    con.commit()
    con.close()


def _run(
    tmp_path: Path,
    slots: dict[str, bool],
    profiles: dict[str, float | None],
    *,
    env_extra: dict[str, str] | None = None,
) -> tuple[str, int]:
    """slots value: True = refresh-capable; False = no-refresh setup-token (365d).

    Writes a plaintext slot file per email (the keychain-fallback path the
    detector reads in a test environment), a state.json index, and a fake
    Chrome profile per `profiles` entry. Returns (stdout, returncode).
    """
    home = tmp_path / "rotator"
    (home / "slots").mkdir(parents=True, exist_ok=True)
    (home / "state.json").write_text(json.dumps({"slots": {e: {} for e in slots}}))
    for email, refreshable in slots.items():
        oauth: dict[str, object] = {"accessToken": "x"}
        if refreshable:
            oauth["refreshToken"] = "r"
            oauth["expiresAt"] = int((time.time() + 8 * 3600) * 1000)
        else:
            # A no-refresh setup-token that is already EXPIRED, so the only thing
            # standing between it and a login nudge is whether a session exists.
            oauth["expiresAt"] = int((time.time() - 86400) * 1000)
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


def _login_line(out: str) -> str:
    """The single [oauth-login-needed] line (the LOGIN nudge), or '' if absent."""
    for ln in out.splitlines():
        if ln.startswith("[oauth-login-needed]"):
            return ln
    return ""


def _stalled_line(out: str) -> str:
    """The single [oauth-capture-stalled] line (the B3 nudge), or '' if absent."""
    for ln in out.splitlines():
        if ln.startswith("[oauth-capture-stalled]"):
            return ln
    return ""


def test_surfaces_only_no_refresh_no_session_slot(tmp_path: Path) -> None:
    """Three slots: refreshable (skip), no-refresh+live-session (B3 stalled nudge, NOT login),
    no-refresh+no-session (the ONLY one that needs a human LOGIN)."""
    out, rc = _run(
        tmp_path,
        {"refresh@x.com": True, "session@x.com": False, "login@x.com": False},
        {"refresh@x.com": 30.0, "session@x.com": 20.0, "login@x.com": None},
    )
    assert rc == 0
    login = _login_line(out)
    assert "login@x.com" in login
    assert "refresh@x.com" not in login   # daemon refreshes it
    assert "session@x.com" not in login   # bootstrap-eligible → not a LOGIN nudge
    assert "1 account(s) need a one-time login" in login
    # The live-session-but-no-refresh account surfaces in the SECONDARY stalled nudge instead.
    stalled = _stalled_line(out)
    assert "session@x.com" in stalled
    assert "refresh@x.com" not in stalled  # self-renews → never stalled


def test_nudge_names_open_login_and_reassures_default_browser(tmp_path: Path) -> None:
    """The nudge points at open-login.sh AND makes explicit it opens a DEDICATED
    Chrome window so the user's default browser (Safari) is untouched."""
    out, _ = _run(tmp_path, {"login@x.com": False}, {"login@x.com": None})
    assert "open-login.sh" in out
    assert "login@x.com" in out
    assert "DEDICATED Chrome window" in out
    assert "default browser is untouched" in out


def test_expired_session_counts_as_no_session(tmp_path: Path) -> None:
    """An EXPIRED claude.ai session (no live sessionKey) cannot bootstrap → login nudge."""
    out, _ = _run(tmp_path, {"login@x.com": False}, {"login@x.com": -2.0})
    assert "[oauth-login-needed]" in out
    assert "login@x.com" in out


def test_no_login_nudge_when_all_refreshable_or_seeded(tmp_path: Path) -> None:
    """Every slot either self-renews or has a live session → NO account needs a LOGIN.
    The seeded-but-no-refresh account still gets the B3 stalled nudge, but the LOGIN line
    is silent."""
    out, rc = _run(
        tmp_path,
        {"refresh@x.com": True, "session@x.com": False},
        {"refresh@x.com": None, "session@x.com": 25.0},
    )
    assert rc == 0
    assert "[oauth-login-needed]" not in out          # no LOGIN needed
    assert "[oauth-capture-stalled]" in out           # but the seeded slot is capture-stalled
    assert "session@x.com" in _stalled_line(out)


def test_fully_silent_when_all_refreshable(tmp_path: Path) -> None:
    """Every slot self-renews (has refreshToken) → BOTH nudges silent (nothing to do)."""
    out, rc = _run(
        tmp_path,
        {"a@x.com": True, "b@x.com": True},
        {"a@x.com": None, "b@x.com": 25.0},
    )
    assert rc == 0
    assert "[oauth-login-needed]" not in out
    assert "[oauth-capture-stalled]" not in out


def test_daily_dedupe_second_run_silent(tmp_path: Path) -> None:
    """Machine-scoped daily dedupe: the same needing-login set emits once/day."""
    slots = {"login@x.com": False}
    profiles: dict[str, float | None] = {"login@x.com": None}
    first, _ = _run(tmp_path, slots, profiles)
    assert "[oauth-login-needed]" in first
    second, rc = _run(tmp_path, slots, profiles)
    assert rc == 0
    assert "[oauth-login-needed]" not in second  # deduped within the same day


def test_capture_stalled_nudge_points_to_log_and_reseed(tmp_path: Path) -> None:
    """B3: a logged-in account whose OAuth capture hasn't completed (no refresh + live
    session) gets the SECONDARY '[oauth-capture-stalled]' nudge pointing at the bootstrap
    LOG and the open-login.sh re-seed — both paths that ACTUALLY EXIST (the earlier manual
    capture command referenced ~/.claude/account-rotator/slot_capture_browser.py, which the
    standalone install does not ship)."""
    out, rc = _run(tmp_path, {"seed@x.com": False}, {"seed@x.com": 20.0})
    assert rc == 0
    stalled = _stalled_line(out)
    assert "[oauth-capture-stalled]" in stalled
    assert "seed@x.com" in stalled
    assert "logged in but their OAuth capture hasn't completed" in stalled
    assert "bootstrap-<email>.log" in stalled
    assert "open-login.sh <email>" in stalled
    # It must NOT be misclassified as a LOGIN nudge.
    assert _login_line(out) == ""


def test_capture_stalled_daily_dedupe(tmp_path: Path) -> None:
    """B3: the stalled nudge is machine-scoped daily-deduped (separate seen-file from the
    login nudge) — the same stalled set emits once/day."""
    slots = {"seed@x.com": False}
    profiles: dict[str, float | None] = {"seed@x.com": 20.0}
    first, _ = _run(tmp_path, slots, profiles)
    assert "[oauth-capture-stalled]" in first
    second, rc = _run(tmp_path, slots, profiles)
    assert rc == 0
    assert "[oauth-capture-stalled]" not in second  # deduped within the same day


def test_opt_in_noop_without_rotator(tmp_path: Path) -> None:
    """No rotator home with a state.json anywhere → silent no-op (opt-in by presence)."""
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
