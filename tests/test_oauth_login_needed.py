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


def test_has_refresh_but_dead_counter_needs_login() -> None:
    """A present refresh token whose exchange keeps FAILING is dead → the detector NUDGES the
    user to re-login even though has_refresh is True (the bug-fix wiring — refresh_failures
    reaches the cascade SSOT; default threshold is 3) (TRDD-HJGR4I5W)."""
    # Below the threshold a transient flake does NOT nudge.
    assert det.slot_needs_login(True, -5.0, False, 1.0, 2) is False
    # At / above the threshold the dead refresh escalates to a login nudge.
    assert det.slot_needs_login(True, -5.0, False, 1.0, 3) is True
    assert det.slot_needs_login(True, None, False, 1.0, 5) is True
    # Default (omitted) refresh_failures=0 stays backward-compatible: no nudge.
    assert det.slot_needs_login(True, -5.0, False, 1.0) is False


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


def test_capture_stalled_dead_refresh_with_session() -> None:
    """TRDD-J9TM3WQK: a DEAD-but-present refresh (failures >= max) WITH a live session is
    'stalled' too — same RENEW_COOKIE set the daemon captures from, so a stuck dead-refresh
    capture still surfaces. A live refresh (failures < max) self-renews; no session is a LOGIN
    nudge, not stalled."""
    mrf = det.cascade.DEFAULT_MAX_REFRESH_FAILURES
    assert det.slot_capture_stalled(True, True, mrf) is True       # dead refresh + session → stalled
    assert det.slot_capture_stalled(True, True, mrf + 4) is True
    assert det.slot_capture_stalled(True, True, mrf - 1) is False  # transient → still self-renews
    assert det.slot_capture_stalled(True, False, mrf) is False     # dead refresh, no session → LOGIN nudge


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
    before=None,
) -> tuple[str, int]:
    """slots value: True = refresh-capable; False = no-refresh setup-token (365d).

    Writes a plaintext slot file per email (the keychain-fallback path the
    detector reads in a test environment), a state.json index, and a fake
    Chrome profile per `profiles` entry. Returns (stdout, returncode).
    """
    home = tmp_path / "rotator"
    (home / "slots").mkdir(parents=True, exist_ok=True)
    (home / "state.json").write_text(json.dumps({"slots": {e: {} for e in slots}}))
    # The detector now gates its keychain reads on the rotator opt-in (TRDD-K3WQ7XM9): a
    # "paused" rotator must never touch the keychain from the heartbeat. These integration
    # tests exercise the opted-in path, so mark the home opted-in.
    (home / "opt-in.flag").touch()
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

    # `before(home)` — last-moment hook for a test that needs an extra file in the rotator
    # home (e.g. the rotation-stuck marker). Runs after the standard fixture so a test can
    # add to it without restating any of it.
    if before is not None:
        before(home)

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
            # These are subprocess tests — never let notify.push's Tier-1 desktop
            # notification actually fire (osascript/notify-send). The notify-routing
            # behaviour itself is exercised in-process below, where notify.push is
            # monkeypatched.
            "CLAUDE_PLUGIN_OPTION_NOTIFY_ENABLED": "false",
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
    session) gets the SECONDARY '[oauth-capture-stalled]' nudge pointing at a log that
    ACTUALLY EXISTS plus the open-login.sh re-seed.

    CORRECTED 2026-08-13 (janitor#258). This test used to assert the literal
    `bootstrap-<email>.log`, under a docstring claiming both paths "ACTUALLY EXIST". Neither
    claim held: that file is opened only when `_invoke_slot_capture` actually LAUNCHES a
    capture, so on a host where the launch was skipped it is absent — and the test pinned the
    defect rather than the contract, which is why the wrong pointer shipped and survived. The
    contract is: name evidence that is there. `rotator.log` is written unconditionally."""
    out, rc = _run(tmp_path, {"seed@x.com": False}, {"seed@x.com": 20.0})
    assert rc == 0
    stalled = _stalled_line(out)
    assert "[oauth-capture-stalled]" in stalled
    assert "seed@x.com" in stalled
    assert "logged in but their OAuth capture hasn't completed" in stalled
    assert "rotator.log" in stalled
    # No capture was launched in this fixture, so no bootstrap log exists -> never named.
    assert "bootstrap-" not in stalled
    assert "open-login.sh <email>" in stalled
    # It must NOT be misclassified as a LOGIN nudge.
    assert _login_line(out) == ""


def test_stalled_nudge_names_the_bootstrap_log_only_when_it_exists(tmp_path: Path) -> None:
    """The other half of the contract: when a capture DID launch, its per-account log is real
    evidence and IS named alongside rotator.log. Proves the omission above is conditional on
    the file's absence, not a blanket removal (janitor#258)."""
    home = tmp_path / "rotator"
    (home / "slots").mkdir(parents=True, exist_ok=True)
    (home / "bootstrap-seed@x.com.log").write_text("consent page timed out\n")
    out, rc = _run(tmp_path, {"seed@x.com": False}, {"seed@x.com": 20.0})
    assert rc == 0
    stalled = _stalled_line(out)
    assert "rotator.log" in stalled
    assert "bootstrap-seed@x.com.log" in stalled


def test_no_message_hard_codes_the_legacy_rotator_home(tmp_path: Path) -> None:
    """THE janitor#258 regression guard. Every path a message names must be RESOLVED from the
    home the detector actually read, never the literal `~/.claude/account-rotator/`.

    The state read was moved onto `configured_rotator_home()` by TRDD-5EUYV08H, but these two
    messages kept the legacy literal — so on a migrated install the detector read the canonical
    dir and then told the reader to look in the legacy one. Both nudges are asserted here
    because the bug was in BOTH and only one was reported."""
    out, rc = _run(
        tmp_path,
        {"login@x.com": False, "seed@x.com": False},
        {"login@x.com": None, "seed@x.com": 20.0},
    )
    assert rc == 0
    login, stalled = _login_line(out), _stalled_line(out)
    assert login and stalled
    for line in (login, stalled):
        assert ".claude/account-rotator" not in line
    # The home-owned artifact (rotator.log) must point INTO the home actually in use...
    assert str(tmp_path) in stalled
    # ...while open-login.sh is a SHIPPED script: this fixture's home has no copy, so the
    # resolver must fall back to the plugin tree. Assert the remedy names a path that is
    # really there — that is the whole contract janitor#258 broke, so test it directly
    # rather than testing which directory it happens to be in.
    for line in (login, stalled):
        named = [tok.strip("`") for tok in line.split() if "open-login.sh" in tok]
        assert named, f"no open-login.sh path in: {line}"
        assert Path(named[0]).is_file(), f"remedy names a missing file: {named[0]}"


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


# ---------------------------------------------------------------------------
# TERTIARY nudge — rotation is IMPOSSIBLE and no human knows (2026-08-20)
#
# The two nudges above cover per-account credential DEATH. They do not cover the
# other dead end: every account alive but USAGE-EXHAUSTED, or no alternate to
# rotate to at all. `rotator._decide()` writes those to stdout and rotator.log,
# and nothing in scripts/ reads that log for them — so the one moment a human is
# the only way forward was the one moment the janitor said nothing, and the
# session just stalled.
# ---------------------------------------------------------------------------


def _write_stuck(home: Path, kind: str, *, age_h: float = 2.0, last_seen_ago_s: int = 30) -> None:
    now = int(time.time())
    (home / "rotation-stuck.json").write_text(json.dumps({
        "kind": kind,
        "detail": "a@x 5h=99%; b@x 7d=100%",
        "first_seen_epoch": now - int(age_h * 3600),
        "last_seen_epoch": now - last_seen_ago_s,
    }), encoding="utf-8")


def test_a_live_stuck_marker_is_reported_to_the_human(tmp_path: Path) -> None:
    """The whole point: an all-accounts-maxed dead end must reach the human, not just a log."""
    out, rc = _run(tmp_path, {"a@x": True}, {"a@x": 30.0},
                   before=lambda home: _write_stuck(home, "all-accounts-maxed"))
    assert rc == 0
    assert "[oauth-rotation-stuck]" in out, out
    assert "all-accounts-maxed" in out
    assert "stall" in out, "the consequence must be stated — that is why the human should care"


def test_a_stale_marker_is_NOT_reported(tmp_path: Path) -> None:
    """The marker clears on a successful rotation, but a host whose rotator STOPPED would
    leave one behind forever. Only report while the condition is still being observed —
    otherwise this nags about a dead end that ended when the rotator did."""
    out, rc = _run(tmp_path, {"a@x": True}, {"a@x": 30.0},
                   before=lambda home: _write_stuck(home, "all-accounts-maxed",
                                                    last_seen_ago_s=7200))
    assert rc == 0
    assert "[oauth-rotation-stuck]" not in out, out


def test_no_marker_means_silence(tmp_path: Path) -> None:
    """The healthy case: absent marker -> not a word. A detector that speaks when nothing is
    wrong trains the reader to ignore it, which is how the 91 unread alerts happened."""
    out, rc = _run(tmp_path, {"a@x": True}, {"a@x": 30.0})
    assert rc == 0
    assert "[oauth-rotation-stuck]" not in out


def test_a_corrupt_marker_is_survived_silently(tmp_path: Path) -> None:
    """Fail-open: an unreadable marker must never break the heartbeat or invent an alarm."""
    def _corrupt(home: Path) -> None:
        (home / "rotation-stuck.json").write_text("{not json", encoding="utf-8")
    out, rc = _run(tmp_path, {"a@x": True}, {"a@x": 30.0}, before=_corrupt)
    assert rc == 0
    assert "[oauth-rotation-stuck]" not in out


def test_each_stuck_kind_names_its_own_remedy(tmp_path: Path) -> None:
    """The three dead ends need DIFFERENT human actions — waiting, adding an account, and
    fixing the network. One generic 'rotation failed' would send the reader down the wrong path."""
    seen = {}
    for kind, expect in (
        ("all-accounts-maxed", "wait"),
        ("no-alternates-configured", "no second account"),
        ("expired-and-offline", "network"),
    ):
        out, rc = _run(tmp_path / kind, {"a@x": True}, {"a@x": 30.0},
                       before=lambda home, k=kind: _write_stuck(home, k))
        assert rc == 0
        assert expect in out.lower(), f"{kind}: expected {expect!r} in {out!r}"
        seen[kind] = out
    assert len({v.split("Detail:")[0] for v in seen.values()}) == 3, "remedies must differ"


# ---------------------------------------------------------------------------
# Phase 1 (TRDD-GZXTSJSR) — wider proactive grace window + urgency escalation +
# the real notify.py human channel. In-process (not subprocess) so notify.push
# can be monkeypatched and never fires a real desktop notification.
# ---------------------------------------------------------------------------


def test_grace_days_default_widened_to_48h(monkeypatch) -> None:
    """Root cause 1: the old 1.0-day default only fired once a token was already
    near-dead. Default must now be 2.0 (48h) so the nudge is proactive."""
    monkeypatch.delenv("CLAUDE_ROTATOR_LOGIN_NUDGE_GRACE_DAYS", raising=False)
    assert det._grace_days() == 2.0


def test_grace_days_bad_env_falls_back_to_the_new_default(monkeypatch) -> None:
    """A non-numeric / non-positive override must fail open onto the (new) default,
    never crash and never silently disable the nudge."""
    monkeypatch.setenv("CLAUDE_ROTATOR_LOGIN_NUDGE_GRACE_DAYS", "not-a-number")
    assert det._grace_days() == 2.0
    monkeypatch.setenv("CLAUDE_ROTATOR_LOGIN_NUDGE_GRACE_DAYS", "-5")
    assert det._grace_days() == 2.0
    monkeypatch.setenv("CLAUDE_ROTATOR_LOGIN_NUDGE_GRACE_DAYS", "7")
    assert det._grace_days() == 7.0


def test_urgency_buckets_escalate_with_worsening_state() -> None:
    """The urgency bucket (drives both notify severity and the escalation dedupe
    key) must climb monotonically as a token approaches / passes expiry, and a
    dead refresh counter is treated as maximal urgency regardless of token_days."""
    assert det._urgency(1.9, 0) == "48h"
    assert det._urgency(1.0, 0) == "24h"
    assert det._urgency(0.5, 0) == "24h"
    assert det._urgency(0.0, 0) == "expired"
    assert det._urgency(-3.0, 0) == "expired"
    assert det._urgency(None, 0) == "expired"
    assert det._urgency(10.0, det.cascade.DEFAULT_MAX_REFRESH_FAILURES) == "dead-refresh"


def _write_login_slot(
    home: Path, email: str, *, expires_in_days: float, refresh_failures: int = 0
) -> None:
    """A single no-refresh, no-session slot at a chosen expiry — the minimal fixture
    for exercising the notify-severity / escalation path directly (bypasses `_run`'s
    hardcoded already-expired slot, so the 48h/24h buckets are reachable)."""
    (home / "slots").mkdir(parents=True, exist_ok=True)
    (home / "state.json").write_text(
        json.dumps({"slots": {email: {"refresh_failures": refresh_failures}}})
    )
    (home / "opt-in.flag").touch()
    oauth = {"accessToken": "x", "expiresAt": int((time.time() + expires_in_days * 86400) * 1000)}
    (home / "slots" / f"{email}.json").write_text(json.dumps({"claudeAiOauth": oauth}))


def _run_inprocess(tmp_path: Path, home_name: str, monkeypatch, capsys, *, before) -> tuple[str, int]:
    """Same env shape as `_run`, but calls `det.main()` in-process so `det.notify.push`
    can be monkeypatched by the caller before invoking this."""
    home = tmp_path / home_name
    before(home)
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    monkeypatch.setenv("CLAUDE_ROTATOR_HOME", str(home))
    monkeypatch.setenv("CLAUDE_ROTATOR_PROFILES", str(tmp_path / "profiles"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "proj"))
    monkeypatch.setenv("HOME", str(tmp_path / "userhome"))
    (tmp_path / "proj").mkdir(exist_ok=True)
    (tmp_path / "userhome").mkdir(exist_ok=True)
    rc = det.main()
    return capsys.readouterr().out, rc


def test_notify_pushed_high_for_a_48h_bucket_account(tmp_path, monkeypatch, capsys) -> None:
    """Acceptance #1: an account within the (now 48h) proactive window fires a HIGH
    notify.push — the decisive fix for root cause 4 (an unattended session never
    reads the passive heartbeat line)."""
    calls = []
    monkeypatch.setattr(det.notify, "push", lambda **kw: calls.append(kw) or "pushed")
    out, rc = _run_inprocess(
        tmp_path, "rotator", monkeypatch, capsys,
        before=lambda home: _write_login_slot(home, "soon@x.com", expires_in_days=1.5),
    )
    assert rc == 0
    assert "[oauth-login-needed]" in out
    assert len(calls) == 1
    assert calls[0]["sev"] == "HIGH"
    assert calls[0]["code"] == "OAUTH-LOGIN-NEEDED"
    assert "soon@x.com" in calls[0]["summary"]


def test_notify_escalates_to_critical_when_expired(tmp_path, monkeypatch, capsys) -> None:
    """An expired token must escalate the notify severity to CRITICAL, not stay at
    the plain HIGH a still-proactive 48h-out account gets."""
    calls = []
    monkeypatch.setattr(det.notify, "push", lambda **kw: calls.append(kw) or "pushed")
    out, rc = _run_inprocess(
        tmp_path, "rotator", monkeypatch, capsys,
        before=lambda home: _write_login_slot(home, "dead@x.com", expires_in_days=-1.0),
    )
    assert rc == 0
    assert len(calls) == 1
    assert calls[0]["sev"] == "CRITICAL"


def test_escalation_sig_re_notifies_same_day_when_bucket_worsens(tmp_path, monkeypatch, capsys) -> None:
    """Root cause 3: the old daily-only dedupe key went silent after one nudge even
    while the login stayed overdue. The bucket-aware signature must re-emit the
    SAME DAY when the account's urgency worsens (48h -> expired)."""
    monkeypatch.setattr(det.notify, "push", lambda **kw: "pushed")
    first, rc1 = _run_inprocess(
        tmp_path, "rotator", monkeypatch, capsys,
        before=lambda home: _write_login_slot(home, "worsen@x.com", expires_in_days=1.9),
    )
    assert rc1 == 0
    assert "[oauth-login-needed]" in first

    second, rc2 = _run_inprocess(
        tmp_path, "rotator", monkeypatch, capsys,
        before=lambda home: _write_login_slot(home, "worsen@x.com", expires_in_days=1.9),
    )
    assert rc2 == 0
    assert "[oauth-login-needed]" not in second  # unchanged bucket -> same-day dedupe holds

    third, rc3 = _run_inprocess(
        tmp_path, "rotator", monkeypatch, capsys,
        before=lambda home: _write_login_slot(home, "worsen@x.com", expires_in_days=-1.0),
    )
    assert rc3 == 0
    assert "[oauth-login-needed]" in third  # worsened to "expired" -> re-notifies same day
