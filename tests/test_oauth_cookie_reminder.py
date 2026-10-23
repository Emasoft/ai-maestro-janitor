"""Tests for the opt-in oauth-cookie-reminder detector.

Builds an isolated temp rotator home (state.json + slot files) and per-account
Chrome profiles (a minimal Cookies sqlite carrying a `sessionKey` at a chosen
expiry), runs the detector as a subprocess with a hermetic env, and asserts the
emit/silent behaviour. Read-only detector; no network, no real keychain.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Mapping
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


def _records(tmp_path: Path) -> dict[str, dict]:
    """The owner remediations the detector recorded (key -> record), {} when none."""
    f = tmp_path / "rotator" / "owner-remediation.json"
    if not f.is_file():
        return {}
    return json.loads(f.read_text()).get("conditions", {})


def _by_condition(tmp_path: Path, condition: str) -> dict[str, dict]:
    return {k: r for k, r in _records(tmp_path).items() if r["condition"] == condition}


def test_silent_when_cookies_healthy(tmp_path: Path) -> None:
    """Cookie 28d (> 7d default) + healthy OAuth: prints nothing and records nothing."""
    out, rc = _run(tmp_path, {"a@example.com": True}, {"a@example.com": 28.0})
    assert rc == 0
    assert out == ""
    assert _records(tmp_path) == {}


def test_near_expiry_records_one_cookie_remediation_and_prints_nothing(tmp_path: Path) -> None:
    """Cookie 3d (< 7d): stdout stays empty (rotator issues never reach an agent, TRDD-1J9B7MWO);
    one owner remediation, condition oauth-cookie-refresh, kind cookie, slot = the email."""
    out, rc = _run(tmp_path, {"a@example.com": True}, {"a@example.com": 3.0})
    assert rc == 0
    assert out == ""
    recs = _by_condition(tmp_path, "oauth-cookie-refresh")
    assert len(recs) == 1
    rec = next(iter(recs.values()))
    assert (rec["kind"], rec["slot"]) == ("cookie", "a@example.com")
    assert "a@example.com" in rec["action"] and "/janitor-refresh-cc-logins" in rec["action"]
    assert _by_condition(tmp_path, "oauth-cookie-refresh-now") == {}  # OAuth is healthy


def test_per_account_action_text_says_no_healthy_oauth_when_none_is_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cookie at risk and the only read slot has no healthy OAuth: the per-account action must not
    claim a safe window."""
    _pass(tmp_path, monkeypatch, {"a@example.com": (False, 0.5)}, {"a@example.com": 3.0})
    rec = next(iter(_by_condition(tmp_path, "oauth-cookie-refresh").values()))
    assert "(no account has healthy OAuth)" in rec["action"]
    assert "safe window" not in rec["action"]


def test_no_session_is_left_to_oauth_login_needed(tmp_path: Path) -> None:
    """No Cookies file at all: that is oauth-login-needed's message, so no cookie record (no
    second popup for the same account)."""
    out, _ = _run(tmp_path, {"a@example.com": True}, {"a@example.com": None})
    assert out == ""
    assert _records(tmp_path) == {}


def test_setup_token_near_expiry_records_setup_token_kind(tmp_path: Path) -> None:
    """Cookie healthy (28d) but a no-refresh setup-token expiring in 10d (< 30d): a setup-token
    record. No account has healthy OAuth, so the machine-wide urgent record exists too."""
    out, _ = _run(
        tmp_path,
        {"s@example.com": 10.0},
        {"s@example.com": 28.0},
        env_extra={"CLAUDE_ROTATOR_SETUP_REMIND_DAYS": "30"},
    )
    assert out == ""
    recs = _by_condition(tmp_path, "oauth-cookie-refresh")
    assert [(r["kind"], r["slot"]) for r in recs.values()] == [("setup-token", "s@example.com")]


@pytest.fixture
def notify_send_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # notify._deliver calls the runner on darwin OR when shutil.which finds notify-send; a never-executed stub makes the Linux tier selectable on any host.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "notify-send"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def _pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    facts: Mapping[str, tuple[bool, float | None]],
    cookies: Mapping[str, float | str | None],
    *,
    state_emails: list[str] | None = None,
):
    """One in-process detector pass. `facts` is what the keychain-aware reader returns (the input
    boundary; an email missing from it is an UNREADABLE slot); `cookies` builds real Cookies
    sqlite files. Returns the loaded detector module."""
    mod = _load_detector()
    home = tmp_path / "rotator"
    home.mkdir(exist_ok=True)
    emails = state_emails if state_emails is not None else list(cookies)
    (home / "state.json").write_text(json.dumps({"slots": {e: {} for e in emails}}))
    (home / "opt-in.flag").touch()
    prof_root = tmp_path / "profiles"
    for email, days in cookies.items():
        db_dir = prof_root / f"chrome-profile-{email}" / "Default"
        if (db_dir / "Cookies").exists():
            (db_dir / "Cookies").unlink()
        if days == "corrupt":  # an existing profile whose DB cannot be read
            (prof_root / f"chrome-profile-{email}" / "Default").mkdir(parents=True, exist_ok=True)
            (prof_root / f"chrome-profile-{email}" / "Default" / "Cookies").write_bytes(b"not sqlite" * 50)
        else:
            assert not isinstance(days, str)
            _make_cookies(prof_root / f"chrome-profile-{email}", days)
    slot_facts = tuple(
        mod.supervisor.SlotFact(email=e, has_refresh=r, expires_days=d) for e, (r, d) in facts.items()
    )
    monkeypatch.setattr(mod.supervisor, "_slot_facts", lambda _home, _now: slot_facts)
    monkeypatch.setenv("CLAUDE_ROTATOR_HOME", str(home))
    monkeypatch.setenv("CLAUDE_ROTATOR_PROFILES", str(prof_root))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "proj"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    (tmp_path / "proj").mkdir(exist_ok=True)
    (tmp_path / "home").mkdir(exist_ok=True)
    assert mod.main() == 0
    return mod


def test_keychain_backed_refresh_slot_is_seen_healthy_no_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """P2 (audit §3.2): OAuth facts come KEYCHAIN-FIRST via supervisor._slot_facts, not the deleted
    plaintext slot file. A refresh-capable keychain-only slot is healthy, so a near-expiry cookie
    records the per-account remediation but NOT the machine-wide urgent one."""
    _pass(tmp_path, monkeypatch, {"a@example.com": (True, None)}, {"a@example.com": 3.0})
    assert capsys.readouterr().out == ""
    slot_email = "a@example.com"
    assert not (tmp_path / "rotator" / "slots" / f"{slot_email}.json").exists()
    assert len(_by_condition(tmp_path, "oauth-cookie-refresh")) == 1
    assert _by_condition(tmp_path, "oauth-cookie-refresh-now") == {}


def test_account_observed_fine_is_cleared_and_unreadable_one_is_kept(
    notify_send_on_path: None,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """a and b both at risk; next pass a is fine (cookie 28d, observed) and b's slot facts are
    unreadable (absent from the reader): a's record and episode end, b's survive."""
    healthy = (True, None)
    mod = _pass(
        tmp_path, monkeypatch,
        {"a@example.com": healthy, "b@example.com": healthy},
        {"a@example.com": 3.0, "b@example.com": 3.0},
    )
    assert {r["slot"] for r in _by_condition(tmp_path, "oauth-cookie-refresh").values()} == {
        "a@example.com", "b@example.com"}
    sent: list[list[str]] = []
    mod.rotator_alert.notify_new_remediations(tmp_path / "rotator", time.time(), runner=sent.append)
    assert len(sent) == 2
    _pass(
        tmp_path, monkeypatch,
        {"a@example.com": healthy},  # b unreadable this pass
        {"a@example.com": 28.0, "b@example.com": 28.0},
    )
    assert {r["slot"] for r in _by_condition(tmp_path, "oauth-cookie-refresh").values()} == {
        "b@example.com"}


def test_unreadable_cookie_db_is_neither_recorded_nor_cleared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slot whose existing cookie DB cannot be read (sqlite error) is not observed: its
    existing record and episode survive the pass."""
    healthy = (True, None)
    _pass(tmp_path, monkeypatch, {"a@example.com": healthy}, {"a@example.com": 3.0})
    assert len(_by_condition(tmp_path, "oauth-cookie-refresh")) == 1
    _pass(tmp_path, monkeypatch, {"a@example.com": healthy}, {"a@example.com": "corrupt"})
    assert len(_by_condition(tmp_path, "oauth-cookie-refresh")) == 1


def test_losing_all_healthy_oauth_adds_exactly_one_urgent_record_and_episode(
    notify_send_on_path: None,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three at-risk accounts, then every account's OAuth goes unhealthy: ONE new machine-wide
    record (condition oauth-cookie-refresh-now, no slot, no kind) and one new notification; the
    three per-account records and episodes are untouched (no N popups for one event). Recovery
    of healthy OAuth clears the one record."""
    emails = ["a@example.com", "b@example.com", "c@example.com"]
    cookies: dict[str, float | None] = {e: 3.0 for e in emails}
    mod = _pass(tmp_path, monkeypatch, {e: (True, None) for e in emails}, cookies)
    sent: list[list[str]] = []
    root = tmp_path / "rotator"
    mod.rotator_alert.notify_new_remediations(root, time.time(), runner=sent.append)
    assert len(sent) == 3
    before = _by_condition(tmp_path, "oauth-cookie-refresh")

    mod = _pass(tmp_path, monkeypatch, {e: (False, 0.5) for e in emails}, cookies)
    now_recs = _by_condition(tmp_path, "oauth-cookie-refresh-now")
    assert len(now_recs) == 1
    rec = next(iter(now_recs.values()))
    assert (rec["slot"], rec["kind"]) == ("", "")
    assert "NOW" in rec["action"]
    after = _by_condition(tmp_path, "oauth-cookie-refresh")
    assert set(after) == set(before)
    assert {k: (r["kind"], r["slot"]) for k, r in after.items()} == {
        k: (r["kind"], r["slot"]) for k, r in before.items()}
    mod.rotator_alert.notify_new_remediations(root, time.time(), runner=sent.append)
    assert len(sent) == 4  # exactly one new notification

    _pass(tmp_path, monkeypatch, {e: (True, None) for e in emails}, cookies)
    assert _by_condition(tmp_path, "oauth-cookie-refresh-now") == {}
    assert len(_by_condition(tmp_path, "oauth-cookie-refresh")) == 3


def test_all_unread_pass_neither_records_nor_clears_the_urgent_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pass where no slot's OAuth facts could be read (locked keychain) says nothing about OAuth
    health: it must not record the urgent record, and must not clear an existing one."""
    cookies: dict[str, float | None] = {"a@example.com": 3.0}
    _pass(tmp_path, monkeypatch, {}, cookies)  # nothing readable, nothing recorded before
    assert _by_condition(tmp_path, "oauth-cookie-refresh-now") == {}
    _pass(tmp_path, monkeypatch, {"a@example.com": (False, 0.5)}, cookies)
    assert len(_by_condition(tmp_path, "oauth-cookie-refresh-now")) == 1
    _pass(tmp_path, monkeypatch, {}, cookies)  # locked keychain: unread
    assert len(_by_condition(tmp_path, "oauth-cookie-refresh-now")) == 1


def test_paused_rotator_records_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the opt-in flag the detector is a no-op, like oauth-login-needed."""
    mod = _load_detector()
    home = tmp_path / "rotator"
    home.mkdir()
    (home / "state.json").write_text(json.dumps({"slots": {"a@example.com": {}}}))
    _make_cookies(tmp_path / "profiles" / "chrome-profile-a@example.com", 3.0)
    monkeypatch.setenv("CLAUDE_ROTATOR_HOME", str(home))
    monkeypatch.setenv("CLAUDE_ROTATOR_PROFILES", str(tmp_path / "profiles"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "proj"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    (tmp_path / "proj").mkdir()
    (tmp_path / "home").mkdir()
    assert mod.main() == 0
    assert _records(tmp_path) == {}

def _now_records(tmp_path: Path) -> dict[str, dict]:
    return _by_condition(tmp_path, "oauth-cookie-refresh-now")


def test_partial_credential_read_with_no_healthy_slot_records_and_names_unreadable_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One credential slot read (unhealthy), one unreadable: an unreadable slot is unusable to the
    rotator too, so the urgent record is made, and its text says how many could not be read."""
    cookies: dict[str, float | None] = {"a@example.com": 3.0, "b@example.com": 28.0}
    _pass(tmp_path, monkeypatch, {"a@example.com": (False, 0.5)}, cookies)
    recs = _now_records(tmp_path)
    assert len(recs) == 1
    assert "1 account(s) could not be read" in next(iter(recs.values()))["action"]


def test_unreadable_count_change_is_the_same_episode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The unreadable count lives only in the text: kind and slot stay empty, so a later pass with
    a different N sends no second notification."""
    cookies: dict[str, float | None] = {"a@example.com": 3.0, "b@example.com": 28.0, "c@example.com": 28.0}
    mod = _pass(tmp_path, monkeypatch, {"a@example.com": (False, 0.5)}, cookies)
    sent: list[list[str]] = []
    root = tmp_path / "rotator"
    mod.rotator_alert.notify_new_remediations(root, time.time(), runner=sent.append)
    now_sent = len(sent)
    mod = _pass(
        tmp_path, monkeypatch,
        {"a@example.com": (False, 0.5), "b@example.com": (False, None)}, cookies,
    )
    assert "1 account(s) could not be read" in next(iter(_now_records(tmp_path).values()))["action"]
    mod.rotator_alert.notify_new_remediations(root, time.time(), runner=sent.append)
    assert len(sent) == now_sent  # only per-account 'a' (already sent) and the same urgent episode


def test_unreadable_only_at_risk_profile_does_not_clear_the_urgent_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing at risk is visible only because the at-risk profile became unreadable: the urgent
    record must survive (partial-read flap)."""
    facts = {"a@example.com": (False, None)}
    _pass(tmp_path, monkeypatch, facts, {"a@example.com": 3.0})
    assert len(_now_records(tmp_path)) == 1
    _pass(tmp_path, monkeypatch, facts, {"a@example.com": "corrupt"})
    assert len(_now_records(tmp_path)) == 1


def test_healthy_read_slot_in_a_partial_read_clears_the_urgent_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read slot with healthy OAuth clears the urgent record even when another slot is unread."""
    cookies: dict[str, float | None] = {"a@example.com": 3.0, "b@example.com": 3.0}
    _pass(tmp_path, monkeypatch, {"a@example.com": (False, 0.5), "b@example.com": (False, 0.5)}, cookies)
    assert len(_now_records(tmp_path)) == 1
    _pass(tmp_path, monkeypatch, {"a@example.com": (True, None)}, cookies)  # b unreadable
    assert _now_records(tmp_path) == {}


def test_account_without_a_profile_does_not_block_the_nothing_at_risk_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An account with no profile at all (never captured) is observed with nothing to read."""
    facts = {"a@example.com": (False, None), "b@example.com": (False, None)}
    _pass(tmp_path, monkeypatch, facts, {"a@example.com": 3.0, "b@example.com": None})
    assert len(_now_records(tmp_path)) == 1
    _pass(tmp_path, monkeypatch, facts, {"a@example.com": 28.0, "b@example.com": None})
    assert _now_records(tmp_path) == {}


def test_readable_profile_with_no_claude_cookie_does_not_block_the_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful read that finds no claude.ai cookie is observed, not unreadable."""
    facts = {"a@example.com": (False, None), "b@example.com": (False, None)}
    _pass(tmp_path, monkeypatch, facts, {"a@example.com": 3.0, "b@example.com": 28.0})
    assert len(_now_records(tmp_path)) == 1
    other = tmp_path / "profiles" / "chrome-profile-b@example.com" / "Default" / "Cookies"
    con = sqlite3.connect(other)  # readable DB with only an unrelated host's cookie
    con.execute("DELETE FROM cookies")
    con.execute("INSERT INTO cookies VALUES ('example.org', 'x', 1)")
    con.commit()
    con.close()
    mod = _load_detector()
    # Re-run without _pass rebuilding the profiles: a is fine now, b has a readable empty DB.
    _make_fine = tmp_path / "profiles" / "chrome-profile-a@example.com" / "Default" / "Cookies"
    con = sqlite3.connect(_make_fine)
    con.execute("DELETE FROM cookies")
    exp = int((time.time() + 28 * 86400 + _EPOCH_OFFSET) * 1_000_000)
    con.execute("INSERT INTO cookies VALUES ('claude.ai', 'sessionKey', ?)", (exp,))
    con.commit()
    con.close()
    slot_facts = tuple(
        mod.supervisor.SlotFact(email=e, has_refresh=False, expires_days=None) for e in facts
    )
    monkeypatch.setattr(mod.supervisor, "_slot_facts", lambda _home, _now: slot_facts)
    assert mod.main() == 0
    assert _now_records(tmp_path) == {}

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
