"""Tests for the opt-in oauth-login-needed detector.

Two layers, both real (no mocks of the code under test):

  * PURE classifier (`slot_needs_login`) truth table — imported by path and
    called directly. Decides whether an account needs a ONE-TIME human login
    because it can neither self-renew (no refreshToken) nor auto-bootstrap (no
    live Chrome session to mint a refresh from).
  * Integration — build an isolated temp rotator home (state.json + plaintext
    slot files) and per-account Chrome profiles (a minimal Cookies sqlite
    carrying a `sessionKey` at a chosen expiry), run the detector as a
    subprocess with a hermetic env, and assert which owner remediations are recorded (the detector
    prints nothing). Read-only detector; no network, no real keychain write, no
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

import pytest

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


def _records(tmp_path: Path) -> dict[str, dict]:
    """The owner remediations the detector recorded in the test rotator home, by record key."""
    path = tmp_path / "rotator" / "owner-remediation.json"
    return json.loads(path.read_text(encoding="utf-8"))["conditions"] if path.is_file() else {}


def _account_keys(recs: dict[str, dict]) -> set[str]:
    """The per-account record keys: a fresh home also gets the weekly top-up record."""
    return {k for k in recs if not k.startswith("oauth-login-topup:")}


def test_surfaces_only_no_refresh_no_session_slot(tmp_path: Path) -> None:
    """Three slots: refreshable (skip), no-refresh+live-session (capture-stalled record, NOT login),
    no-refresh+no-session (the ONLY one that needs a human LOGIN). The detector PRINTS NOTHING
    (USER ruling 2026-10-21): everything lands in owner-remediation.json."""
    out, rc = _run(
        tmp_path,
        {"refresh@x.com": True, "session@x.com": False, "login@x.com": False},
        {"refresh@x.com": 30.0, "session@x.com": 20.0, "login@x.com": None},
    )
    assert rc == 0 and out == ""
    recs = _records(tmp_path)
    assert _account_keys(recs) == {"oauth-login-needed:expired:login@x.com", "oauth-capture-stalled:session@x.com"}
    assert recs["oauth-login-needed:expired:login@x.com"]["slot"] == "login@x.com"


def test_nudge_names_open_login_and_reassures_default_browser(tmp_path: Path) -> None:
    """The remedy points at open-login.sh AND makes explicit it opens a DEDICATED
    Chrome window so the user's default browser (Safari) is untouched."""
    _run(tmp_path, {"login@x.com": False}, {"login@x.com": None})
    action = _records(tmp_path)["oauth-login-needed:expired:login@x.com"]["action"]
    assert "open-login.sh" in action
    assert "login@x.com" in action
    assert "DEDICATED Chrome window" in action
    assert "default browser is untouched" in action


def test_expired_session_counts_as_no_session(tmp_path: Path) -> None:
    """An EXPIRED claude.ai session (no live sessionKey) cannot bootstrap → login remediation."""
    out, _ = _run(tmp_path, {"login@x.com": False}, {"login@x.com": -2.0})
    assert out == ""
    assert "oauth-login-needed:expired:login@x.com" in _records(tmp_path)


def test_no_login_nudge_when_all_refreshable_or_seeded(tmp_path: Path) -> None:
    """Every slot either self-renews or has a live session → NO account needs a LOGIN.
    The seeded-but-no-refresh account is capture-stalled, but no login record exists."""
    out, rc = _run(
        tmp_path,
        {"refresh@x.com": True, "session@x.com": False},
        {"refresh@x.com": None, "session@x.com": 25.0},
    )
    assert rc == 0 and out == ""
    assert _account_keys(_records(tmp_path)) == {"oauth-capture-stalled:session@x.com"}


def test_fully_silent_when_all_refreshable(tmp_path: Path) -> None:
    """Every slot self-renews (has refreshToken) → nothing printed, no account record."""
    out, rc = _run(
        tmp_path,
        {"a@x.com": True, "b@x.com": True},
        {"a@x.com": None, "b@x.com": 25.0},
    )
    assert rc == 0 and out == ""
    assert not any(k.startswith(("oauth-login-needed", "oauth-capture-stalled")) for k in _records(tmp_path))


def test_a_second_run_refreshes_the_same_record_and_prints_nothing(tmp_path: Path) -> None:
    """The detector runs in every session: a second run re-stamps the SAME record (the daemon's
    freshness signal) and never creates a second one or prints anything."""
    slots = {"login@x.com": False}
    profiles: dict[str, float | None] = {"login@x.com": None}
    first, _ = _run(tmp_path, slots, profiles)
    key = "oauth-login-needed:expired:login@x.com"
    seen1 = _records(tmp_path)[key]["last_seen"]
    time.sleep(1.1)
    second, rc = _run(tmp_path, slots, profiles)
    assert rc == 0 and first == "" and second == ""
    recs = _records(tmp_path)
    assert [k for k in recs if k.startswith("oauth-login-needed")] == [key]
    assert recs[key]["last_seen"] > seen1


def test_capture_stalled_remedy_points_to_log_and_reseed(tmp_path: Path) -> None:
    """B3: a logged-in account whose OAuth capture hasn't completed (no refresh + live
    session) gets a capture-stalled remediation pointing at a log that ACTUALLY EXISTS plus the
    open-login.sh re-seed.

    CORRECTED 2026-08-13 (janitor#258). This test used to assert the literal
    `bootstrap-<email>.log`, under a docstring claiming both paths "ACTUALLY EXIST". Neither
    claim held: that file is opened only when `_invoke_slot_capture` actually LAUNCHES a
    capture, so on a host where the launch was skipped it is absent. The contract is: name
    evidence that is there. `rotator.log` is written unconditionally."""
    out, rc = _run(tmp_path, {"seed@x.com": False}, {"seed@x.com": 20.0})
    assert rc == 0 and out == ""
    recs = _records(tmp_path)
    action = recs["oauth-capture-stalled:seed@x.com"]["action"]
    assert "seed@x.com" in action
    assert "logged in but its OAuth capture hasn't completed" in action
    assert "rotator.log" in action
    # No capture was launched in this fixture, so no bootstrap log exists -> never named.
    assert "bootstrap-" not in action
    assert "open-login.sh" in action
    # It must NOT be misclassified as a LOGIN remediation.
    assert not any(k.startswith("oauth-login-needed") for k in recs)


def test_stalled_remedy_names_the_bootstrap_log_only_when_it_exists(tmp_path: Path) -> None:
    """The other half of the contract: when a capture DID launch, its per-account log is real
    evidence and IS named alongside rotator.log. Proves the omission above is conditional on
    the file's absence, not a blanket removal (janitor#258)."""
    home = tmp_path / "rotator"
    (home / "slots").mkdir(parents=True, exist_ok=True)
    (home / "bootstrap-seed@x.com.log").write_text("consent page timed out\n")
    out, rc = _run(tmp_path, {"seed@x.com": False}, {"seed@x.com": 20.0})
    assert rc == 0
    action = _records(tmp_path)["oauth-capture-stalled:seed@x.com"]["action"]
    assert "rotator.log" in action
    assert "bootstrap-seed@x.com.log" in action


def test_no_message_hard_codes_the_legacy_rotator_home(tmp_path: Path) -> None:
    """THE janitor#258 regression guard. Every path a remediation names must be RESOLVED from the
    home the detector actually read, never the literal `~/.claude/account-rotator/`.

    The state read was moved onto `configured_rotator_home()` by TRDD-5EUYV08H, but these two
    messages kept the legacy literal — so on a migrated install the detector read the canonical
    dir and then told the reader to look in the legacy one. Both remediations are asserted here
    because the bug was in BOTH and only one was reported."""
    out, rc = _run(
        tmp_path,
        {"login@x.com": False, "seed@x.com": False},
        {"login@x.com": None, "seed@x.com": 20.0},
    )
    assert rc == 0
    recs = _records(tmp_path)
    login = recs["oauth-login-needed:expired:login@x.com"]["action"]
    stalled = recs["oauth-capture-stalled:seed@x.com"]["action"]
    for line in (login, stalled):
        assert ".claude/account-rotator" not in line
    # The home-owned artifact (rotator.log) must point INTO the home actually in use...
    assert str(tmp_path) in stalled
    # ...while open-login.sh is a SHIPPED script: this fixture's home has no copy, so the
    # resolver must fall back to the plugin tree. Assert the remedy names a path that is
    # really there — that is the whole contract janitor#258 broke.
    for line in (login, stalled):
        named = [tok.strip("`") for tok in line.split() if "open-login.sh" in tok]
        assert named, f"no open-login.sh path in: {line}"
        assert Path(named[0]).is_file(), f"remedy names a missing file: {named[0]}"


def test_the_detector_never_notifies_and_never_prints(tmp_path: Path, monkeypatch, capsys) -> None:
    """USER ruling 2026-10-21: no per-session notification and no agent-visible output. Every
    notification entry point is replaced by a tripwire; a run over a login-needed account, a
    stalled-capture account, a live stuck marker and a due top-up must not touch any of them."""
    tripped: list[str] = []
    monkeypatch.setattr(det.rotator_alert.notify, "push", lambda **kw: tripped.append("push"))
    monkeypatch.setattr(det.rotator_alert.notify, "_deliver", lambda *a, **kw: tripped.append("_deliver"))
    monkeypatch.setattr(det.rotator_alert.notify, "notify_episode", lambda **kw: tripped.append("episode"))

    def fixture(home: Path) -> None:
        _write_login_slot(home, "stalled@example.com", expires_in_days=-1.0)
        _make_cookies(tmp_path / "profiles" / "chrome-profile-stalled@example.com", 2.0)
        (home / "rotation-stuck.json").write_text(
            json.dumps({"kind": "all-accounts-maxed", "detail": "d", "first_seen_epoch": int(time.time()) - 7200,
                        "last_seen_epoch": int(time.time()) - 30})
        )

    out, rc = _run_inprocess(tmp_path, "rotator", monkeypatch, capsys, before=fixture)
    assert rc == 0 and out == ""
    assert tripped == []
    recs = _records(tmp_path)
    assert "oauth-capture-stalled:stalled@example.com" in recs
    assert any(k.startswith("oauth-login-topup:") for k in recs)


@pytest.mark.skipif(sys.platform != "darwin", reason="counts banners through a fake osascript")
def test_a_stalled_daemon_is_notified_once_across_all_session_heartbeats(tmp_path: Path) -> None:
    """A hung or dead daemon cannot report itself, so the heartbeat-side detector does - under
    the daemon's episode key in the machine-wide store. Three sessions' heartbeats (three real
    detector processes) raise ONE banner, print nothing, and a fresh tick raises none."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    banners = tmp_path / "banners.txt"
    exe = bindir / "osascript"
    exe.write_text(f'#!/bin/sh\necho "$@" >> "{banners}"\n')
    exe.chmod(0o755)
    env_extra = {
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "CLAUDE_PLUGIN_OPTION_NOTIFY_ENABLED": "true",
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "gs"),
    }

    def stale_tick(home: Path, age_s: float) -> None:
        stamp = home / "tick-completed.ts"
        stamp.write_text("0")
        at = time.time() - age_s
        os.utime(stamp, (at, at))

    for _ in range(3):
        out, rc = _run(tmp_path, {"a@x": True}, {"a@x": 30.0}, env_extra=env_extra,
                       before=lambda home: stale_tick(home, 700))
        assert rc == 0 and out == ""
    assert banners.read_text().count("janitor") >= 1
    assert len(banners.read_text().splitlines()) == 1
    assert "stopped ticking" in banners.read_text()
    banners.unlink()
    (tmp_path / "gs" / "notify-sent.txt").unlink()
    out, rc = _run(tmp_path, {"a@x": True}, {"a@x": 30.0}, env_extra=env_extra,
                   before=lambda home: stale_tick(home, 30))
    assert rc == 0 and out == "" and not banners.exists()


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


def test_a_live_stuck_marker_is_not_the_detectors_business(tmp_path: Path) -> None:
    """The rotation-stuck verdict reaches the user through the daemon's rotator_alert (one
    notification per kind). The detector no longer words it from `stuck_text`: that text printed
    the false all-accounts-maxed verdict into agent context (TRDD-1J9B7MWO)."""
    out, rc = _run(tmp_path, {"a@x": True}, {"a@x": 30.0},
                   before=lambda home: _write_stuck(home, "all-accounts-maxed"))
    assert rc == 0
    assert out == ""
    assert not any("stuck" in k for k in _records(tmp_path))


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


def test_a_48h_bucket_account_is_recorded_with_its_urgency_as_the_kind(tmp_path, monkeypatch, capsys) -> None:
    """An account within the (48h) proactive window gets a login remediation whose kind is its
    urgency bucket (the daemon notifies it once per episode; the detector prints nothing)."""
    out, rc = _run_inprocess(
        tmp_path, "rotator", monkeypatch, capsys,
        before=lambda home: _write_login_slot(home, "soon@x.com", expires_in_days=1.5),
    )
    assert rc == 0 and out == ""
    rec = _records(tmp_path)["oauth-login-needed:48h:soon@x.com"]
    assert rec["condition"] == "oauth-login-needed" and rec["kind"] == "48h" and rec["slot"] == "soon@x.com"
    assert "soon@x.com" in rec["action"]


def test_an_expired_token_is_recorded_as_the_expired_bucket(tmp_path, monkeypatch, capsys) -> None:
    """An expired token is the maximal-urgency bucket, a different episode from the 48h one."""
    out, rc = _run_inprocess(
        tmp_path, "rotator", monkeypatch, capsys,
        before=lambda home: _write_login_slot(home, "dead@x.com", expires_in_days=-1.0),
    )
    assert rc == 0 and out == ""
    assert "oauth-login-needed:expired:dead@x.com" in _records(tmp_path)


def test_a_worsening_account_supersedes_its_old_record(tmp_path, monkeypatch, capsys) -> None:
    """The urgency bucket is part of the episode key: an account that worsens (48h -> expired)
    gets a NEW record (so the daemon notifies again) and ONE record per account stays - the old
    bucket's record is superseded; an unchanged account re-stamps its record."""
    for days, key in ((1.9, "oauth-login-needed:48h:worsen@x.com"), (1.9, "oauth-login-needed:48h:worsen@x.com"),
                      (-1.0, "oauth-login-needed:expired:worsen@x.com")):
        out, rc = _run_inprocess(
            tmp_path, "rotator", monkeypatch, capsys,
            before=lambda home, d=days: _write_login_slot(home, "worsen@x.com", expires_in_days=d),
        )
        assert rc == 0 and out == ""
        assert key in _records(tmp_path)
    assert {k for k in _records(tmp_path) if k.startswith("oauth-login-needed")} == {
        "oauth-login-needed:expired:worsen@x.com"}


class _Banners:
    def __init__(self) -> None:
        self.argvs: list[list[str]] = []

    def __call__(self, argv: list[str]) -> None:
        self.argvs.append(argv)


def _write_fine_slot(home: Path, email: str) -> None:
    """A self-renewing account (refresh token, far expiry): never needs a login."""
    (home / "slots").mkdir(parents=True, exist_ok=True)
    (home / "state.json").write_text(json.dumps({"slots": {email: {"refresh_failures": 0}}}))
    (home / "opt-in.flag").touch()
    oauth = {"accessToken": "x", "refreshToken": "r", "expiresAt": int((time.time() + 30 * 86400) * 1000)}
    (home / "slots" / f"{email}.json").write_text(json.dumps({"claudeAiOauth": oauth}))


# The runner is only invoked by notify._deliver on darwin (osascript) or with notify-send installed; CI ubuntu has neither.
@pytest.mark.skipif(sys.platform != "darwin", reason="counts banners through the darwin osascript tier")
def test_an_account_seen_fine_ends_its_episode_and_sparse_heartbeats_do_not_renotify(
    tmp_path, monkeypatch, capsys
) -> None:
    """Heartbeats hours apart are NOT a clear (an unchanged account notifies once); the detector
    seeing the account fine deletes the record and ends the episode, so a relapse after the flap
    window notifies again and a relapse inside it does not."""
    import notify  # type: ignore[import-not-found]

    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS", "0")
    banners = _Banners()
    base = 1_800_000_000.0

    def beat(at: float, needing: bool) -> None:
        monkeypatch.setattr(det.time, "time", lambda: at)
        _run_inprocess(
            tmp_path, "rotator", monkeypatch, capsys,
            before=(lambda h: _write_login_slot(h, "a@x.com", expires_in_days=-1.0))
            if needing else (lambda h: _write_fine_slot(h, "a@x.com")),
        )
        det.rotator_alert.notify_new_remediations(tmp_path / "rotator", at, runner=banners)

    beat(base, True)
    assert len(banners.argvs) == 1
    beat(base + 7200, True)  # the next heartbeat, 2 h later: same unchanged episode
    assert len(banners.argvs) == 1
    beat(base + 7300, False)  # seen fine: record deleted, episode ended
    assert _account_keys(_records(tmp_path)) == set()
    beat(base + 7400, True)  # relapse inside the flap window: same episode
    assert len(banners.argvs) == 1
    beat(base + 7500, False)
    beat(base + 7500 + notify.EPISODE_FLAP_S + 1, True)  # relapse after the window: new episode
    assert len(banners.argvs) == 2



def _record_for(home: Path, email: str, kind: str = "expired") -> None:
    det.rotator_alert.record_owner_remediation(
        home, "oauth-login-needed", f"account {email} needs a one-time login", time.time(),
        kind=kind, slot=email,
    )


def test_an_account_not_read_this_pass_keeps_its_record_and_episode(tmp_path, monkeypatch, capsys) -> None:
    """_slot_facts skips a slot whose blob is unreadable: that account was NOT observed, so its
    record must survive (only the account actually read and found fine is cleared)."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS", "0")

    def before(home: Path) -> None:
        _write_fine_slot(home, "read@example.com")
        _record_for(home, "read@example.com")
        _record_for(home, "unread@example.com")

    _run_inprocess(tmp_path, "rotator", monkeypatch, capsys, before=before)
    keys = _account_keys(_records(tmp_path))
    assert not any("read@example.com" in k and "unread" not in k for k in keys)  # observed fine: cleared
    assert any(k.endswith(":unread@example.com") for k in keys)  # unobserved: kept


def test_a_readable_but_degraded_blob_is_not_observed_fine(tmp_path, monkeypatch, capsys) -> None:
    """A readable blob with no refresh token and no expiry still needs a login: it is recorded,
    never cleared as fine."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_LOGIN_TOPUP_EVERY_DAYS", "0")
    email = "deg@example.com"

    def before(home: Path) -> None:
        (home / "slots").mkdir(parents=True)
        (home / "state.json").write_text(json.dumps({"slots": {email: {"refresh_failures": 0}}}))
        (home / "opt-in.flag").touch()
        (home / "slots" / f"{email}.json").write_text(json.dumps({"claudeAiOauth": {"accessToken": "x"}}))
        _record_for(home, email)

    _run_inprocess(tmp_path, "rotator", monkeypatch, capsys, before=before)
    assert any(k.endswith(f":{email}") for k in _account_keys(_records(tmp_path)))


def test_the_server_owns_probe_never_runs_with_the_rotator_off(tmp_path, monkeypatch, capsys) -> None:
    """A rotator home without the opt-in flag never evaluates the server-owns probe."""
    calls: list[int] = []
    monkeypatch.setattr(det.supervisor, "_server_owns_chores", lambda: calls.append(1) or False)

    def off(home: Path) -> None:
        home.mkdir(parents=True)
        (home / "state.json").write_text(json.dumps({"slots": {}}))

    _run_inprocess(tmp_path, "rotator", monkeypatch, capsys, before=off)
    assert calls == []
    _run_inprocess(tmp_path, "rotator_on", monkeypatch, capsys, before=lambda h: _write_fine_slot(h, "a@x.com"))
    assert calls == [1]


# ---------------------------------------------------------------------------
# TRDD-TK529Q0F, superseded by TRDD-1J9B7MWO (USER ruling 2026-10-21): the rotation-stuck
# verdict reaches the user through the daemon (rotator_alert, one notification per kind), never
# through this per-session detector and never into agent context. The tests below pin that the
# detector stays silent for every stuck-marker shape.
# ---------------------------------------------------------------------------


