"""Tests for the OAuth-rotator supervisor (scripts/oauth_rotator/supervisor.py).

Since TRDD-f892e109 decision 3 the supervisor is ALERT-ONLY — the launchd agent
is gone and the daemon's 60 s oauth-rotator-tick Task owns rotation, so there is
nothing to heal. The pure decision core `diagnose(facts)` is exercised
exhaustively (opt-in gate, pinning-env alert, non-macos alert, the per-slot
setup-token-expiry alert). The I/O bits — `opt_in_present`, `_slot_facts`,
`gather_facts`, `apply` — run against tmp dirs. No mocks anywhere.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SUP_PY = _HERE.parent / "scripts" / "oauth_rotator" / "supervisor.py"


def _load():
    spec = importlib.util.spec_from_file_location("supervisor_under_test", _SUP_PY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so frozen @dataclass can resolve cls.__module__.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


sup = _load()


def _facts(**kw):
    """A healthy, opted-in, macOS Facts; override fields per test."""
    base = dict(opt_in=True, on_macos=True, pinning_env=(), slots=())
    base.update(kw)
    return sup.Facts(**base)


def _codes(findings) -> set[str]:
    return {f.code for f in findings}


def test_opt_out_is_total_noop() -> None:
    """No opt-in flag → diagnose returns nothing, whatever else is wrong."""
    f = _facts(opt_in=False, pinning_env=("ANTHROPIC_API_KEY",))
    assert sup.diagnose(f) == []


def test_healthy_system_has_no_findings() -> None:
    """Opted-in on macOS + clean env + no slots → silent."""
    assert sup.diagnose(_facts()) == []


def test_pinning_env_alerts_per_var() -> None:
    """Each pinning env var that overrides the keychain → one 'pinning-env' alert."""
    f = _facts(pinning_env=("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"))
    findings = sup.diagnose(f)
    pin = [x for x in findings if x.code == "pinning-env"]
    assert len(pin) == 2
    assert "ANTHROPIC_API_KEY" in pin[0].message


def test_non_macos_alerts_only() -> None:
    """Opted-in off macOS → a single 'non-macos' alert (keychain swap can't run here)."""
    findings = sup.diagnose(_facts(on_macos=False))
    assert _codes(findings) == {"non-macos"}


def test_setup_token_expiry_alerts_only_for_no_refresh() -> None:
    """A no-refresh setup-token within the remind window alerts; a full-OAuth
    slot (has_refresh) does NOT alert even when its own expiry is near."""
    soon = sup.SETUP_REMIND_DAYS - 1
    setup = sup.SlotFact(email="s@x.com", has_refresh=False, expires_days=soon)
    full = sup.SlotFact(email="f@x.com", has_refresh=True, expires_days=soon)
    findings = sup.diagnose(_facts(slots=(setup, full)))
    alerts = [x for x in findings if x.code == "setup-token-expiring"]
    assert len(alerts) == 1
    assert "s@x.com" in alerts[0].message
    # A no-refresh token NOT yet inside the window does not alert:
    far = sup.SlotFact(email="ok@x.com", has_refresh=False,
                       expires_days=sup.SETUP_REMIND_DAYS + 100)
    assert not [x for x in sup.diagnose(_facts(slots=(far,))) if x.code == "setup-token-expiring"]


def test_slot_facts_reads_refresh_and_expiry(tmp_path: Path) -> None:
    """_slot_facts parses has_refresh + expires_days from real slot JSON files."""
    slots = tmp_path / "slots"
    slots.mkdir()
    now = 1_780_000_000.0  # realistic epoch so ms-values clear the >1e12 ms/sec heuristic
    # full OAuth: refresh present, expires in 2 days (ms epoch)
    (slots / "full@x.com.json").write_text(json.dumps({"claudeAiOauth": {
        "accessToken": "a", "refreshToken": "r",
        "expiresAt": int((now + 2 * 86400) * 1000)}}))
    # setup-token: no refresh, expires in 5 days (ms epoch)
    (slots / "setup@x.com.json").write_text(json.dumps({"claudeAiOauth": {
        "accessToken": "a", "refreshToken": None,
        "expiresAt": int((now + 5 * 86400) * 1000)}}))
    # _slot_facts now gates its keychain read on the rotator opt-in (TRDD-K3WQ7XM9); mark the
    # root opted-in so this test exercises the actual slot-parsing behaviour it asserts.
    (tmp_path / "opt-in.flag").touch()
    facts = {s.email: s for s in sup._slot_facts(tmp_path, now)}
    assert facts["full@x.com"].has_refresh is True
    assert abs(facts["full@x.com"].expires_days - 2.0) < 0.01
    assert facts["setup@x.com"].has_refresh is False
    assert abs(facts["setup@x.com"].expires_days - 5.0) < 0.01


def test_slot_facts_gated_on_opt_in_never_reads_keychain(tmp_path: Path) -> None:
    """KEYCHAIN-SAFETY GATE (TRDD-K3WQ7XM9): with NO opt-in.flag, _slot_facts returns () and
    NEVER reads a slot — even though real slot files (and a state.json index) exist. This is
    the choke-point both oauth-login-needed and oauth-cookie-reminder reach directly; without
    the gate a "paused" rotator kept reading the OS keychain from the heartbeat, and a LOCKED
    login keychain turned every read into a GUI unlock-prompt flood (the 2026-07-09 incident)."""
    slots = tmp_path / "slots"
    slots.mkdir()
    now = 1_780_000_000.0
    (tmp_path / "state.json").write_text(json.dumps({"slots": {"a@x.com": {}}}))
    (slots / "a@x.com.json").write_text(json.dumps({"claudeAiOauth": {
        "accessToken": "a", "refreshToken": "r", "expiresAt": int((now + 2 * 86400) * 1000)}}))
    # No opt-in.flag → the gate must short-circuit BEFORE any keychain / slot read.
    assert sup.opt_in_present(root=tmp_path) is False
    assert sup._slot_facts(tmp_path, now) == ()
    # And once opted in, the very same fixture DOES read the slot (proves () was the gate, not
    # a parse failure).
    (tmp_path / "opt-in.flag").touch()
    facts = sup._slot_facts(tmp_path, now)
    assert [f.email for f in facts] == ["a@x.com"]


def test_opt_in_present_tracks_the_flag(tmp_path: Path) -> None:
    """opt_in_present() is the daemon tick gate: True iff opt-in.flag exists."""
    assert sup.opt_in_present(root=tmp_path) is False
    (tmp_path / "opt-in.flag").write_text("on")
    assert sup.opt_in_present(root=tmp_path) is True


def test_gather_facts_opt_out_when_flag_absent(tmp_path: Path) -> None:
    """gather_facts against a root with no opt-in.flag → opt_in False, no slots,
    and diagnose stays a no-op (never touches launchd/keychain)."""
    facts = sup.gather_facts(root=tmp_path, now=1_000_000.0)
    assert facts.opt_in is False
    assert facts.slots == ()
    assert sup.diagnose(facts) == []


def test_apply_records_alerts_and_logs() -> None:
    """apply() records every alert finding's code and logs it (the supervisor
    heals nothing now that the daemon owns the tick)."""
    logs: list[str] = []
    findings = [
        sup.Finding("pinning-env", "$ANTHROPIC_API_KEY set"),
        sup.Finding("setup-token-expiring", "s@x.com expiring"),
    ]
    res = sup.apply(findings, log=logs.append)
    assert res.alerts == ["pinning-env", "setup-token-expiring"]
    assert any("pinning-env" in m for m in logs)


# ── F4 (TRDD-7PYTX4E9): tick-liveness alert — the tick machinery must be observed.
# The 2026-07-08 tick hung on a keychain ACL prompt and stopped silently for 30+ min
# with zero alarms; a stale tick-completion stamp while the daemon is alive is that
# silence made loud.

def test_tick_stalled_alerts_when_daemon_alive_and_stamp_stale() -> None:
    """daemon alive + last tick completion older than the stall window → 'tick-stalled'."""
    f = _facts(daemon_alive=True, tick_completed_age_s=sup.TICK_STALL_ALERT_S + 1)
    findings = sup.diagnose(f)
    stalled = [x for x in findings if x.code == "tick-stalled"]
    assert len(stalled) == 1
    assert "effectively OFF" in stalled[0].message
    assert "has not COMPLETED" in stalled[0].message


def test_tick_stalled_alerts_when_stamp_never_written() -> None:
    """A None age (stamp absent/garbage) counts as stalled once this version ships —
    every completed tick stamps, so a persistent None is a real signal, not noise."""
    f = _facts(daemon_alive=True, tick_completed_age_s=None)
    stalled = [x for x in sup.diagnose(f) if x.code == "tick-stalled"]
    assert len(stalled) == 1
    assert "never" in stalled[0].message


def test_tick_fresh_stamp_no_alert() -> None:
    """A recent tick completion (well within the window) → no tick-stalled alert."""
    f = _facts(daemon_alive=True, tick_completed_age_s=30.0)
    assert not [x for x in sup.diagnose(f) if x.code == "tick-stalled"]


def test_tick_stall_suppressed_when_daemon_down() -> None:
    """daemon NOT alive → no tick-stalled alert even with a stale/None stamp: a dead
    daemon is the daemon's own problem (its liveness watchdog owns it), not a tick stall."""
    assert not [x for x in sup.diagnose(_facts(daemon_alive=False, tick_completed_age_s=99_999.0))
                if x.code == "tick-stalled"]
    assert not [x for x in sup.diagnose(_facts(daemon_alive=False, tick_completed_age_s=None))
                if x.code == "tick-stalled"]


def test_tick_completed_age_reads_real_stamp(tmp_path: Path) -> None:
    """_tick_completed_age_s reads tick-completed.ts as an epoch and returns the age;
    an absent OR garbage stamp yields None (which diagnose treats as stalled)."""
    now = 2_000_000.0
    assert sup._tick_completed_age_s(tmp_path, now) is None            # absent
    (tmp_path / "tick-completed.ts").write_text(str(int(now - 42)))
    assert abs(sup._tick_completed_age_s(tmp_path, now) - 42.0) < 0.01  # real age
    (tmp_path / "tick-completed.ts").write_text("not-a-number")
    assert sup._tick_completed_age_s(tmp_path, now) is None            # garbage


def test_gather_facts_populates_tick_liveness(tmp_path: Path, monkeypatch) -> None:
    """gather_facts (opted-in) reads the tick-completion stamp and the daemon-alive
    probe into Facts, so diagnose can fire the stall alert. _daemon_alive is stubbed
    (the real probe imports the global daemon state, absent in the test harness)."""
    (tmp_path / "opt-in.flag").write_text("on")
    now = 3_000_000.0
    (tmp_path / "tick-completed.ts").write_text(str(int(now - (sup.TICK_STALL_ALERT_S + 5))))
    monkeypatch.setattr(sup, "_daemon_alive", lambda: True)
    facts = sup.gather_facts(root=tmp_path, now=now)
    assert facts.daemon_alive is True
    assert facts.tick_completed_age_s is not None
    assert facts.tick_completed_age_s > sup.TICK_STALL_ALERT_S
    assert "tick-stalled" in {x.code for x in sup.diagnose(facts)}


def test_cookie_leg_stuck_alerts_only_past_threshold() -> None:
    """D3 (TRDD-WBYFTU2L): a slot that has been unable to self-renew LONGER than
    COOKIE_LEG_ALERT_S alerts (the human-only cascade legs have no daemon actor, so
    the alert IS the actuation); at/below the threshold, or when self-renewable
    (age None), it stays silent."""
    stuck = sup.SlotFact(email="stuck@x.com", has_refresh=False, expires_days=0.1,
                         cannot_self_renew_age_s=sup.COOKIE_LEG_ALERT_S + 10)
    fresh = sup.SlotFact(email="fresh@x.com", has_refresh=False, expires_days=0.1,
                         cannot_self_renew_age_s=sup.COOKIE_LEG_ALERT_S - 10)
    healthy = sup.SlotFact(email="ok@x.com", has_refresh=True, expires_days=0.3,
                           cannot_self_renew_age_s=None)
    findings = [x for x in sup.diagnose(_facts(slots=(stuck, fresh, healthy)))
                if x.code == "cookie-leg-stuck"]
    assert len(findings) == 1
    assert "stuck@x.com" in findings[0].message
    assert "/janitor-refresh-cc-logins" in findings[0].message


def test_track_cannot_self_renew_stamps_ages_and_clears(tmp_path: Path) -> None:
    """The sidecar (cookie-leg-since.json) records the FIRST-SEEN epoch of each slot's
    cannot-self-renew state: age grows across calls while the state persists, resets to
    None (entry pruned) the moment the slot regains a usable refresh path, and a healthy
    long-lived no-refresh SETUP token (300d runway) never enters the map at all — its
    <30d case is setup-token-expiring's job, not a login alert's."""
    now = 4_000_000.0
    dead = sup.SlotFact(email="dead@x.com", has_refresh=False, expires_days=0.2)
    setup = sup.SlotFact(email="setup@x.com", has_refresh=False, expires_days=300.0)
    first = {s.email: s for s in sup._track_cannot_self_renew(tmp_path, (dead, setup), now)}
    assert first["dead@x.com"].cannot_self_renew_age_s == 0.0
    assert first["setup@x.com"].cannot_self_renew_age_s is None      # plenty of runway
    assert json.loads((tmp_path / "cookie-leg-since.json").read_text()) == {"dead@x.com": now}
    # An hour later, still dead → the age is measured from FIRST-SEEN, not per-call.
    later = {s.email: s for s in sup._track_cannot_self_renew(tmp_path, (dead,), now + 3600)}
    assert abs(later["dead@x.com"].cannot_self_renew_age_s - 3600.0) < 0.01
    # The slot regains a working refresh → age None and the sidecar entry is pruned.
    revived = sup.SlotFact(email="dead@x.com", has_refresh=True, expires_days=0.2)
    cleared = {s.email: s for s in sup._track_cannot_self_renew(tmp_path, (revived,), now + 7200)}
    assert cleared["dead@x.com"].cannot_self_renew_age_s is None
    assert json.loads((tmp_path / "cookie-leg-since.json").read_text()) == {}


def test_track_cannot_self_renew_dead_refresh_counts_as_unrenewable(tmp_path: Path) -> None:
    """A refresh token that EXISTS but keeps failing (refresh_failures >= the cascade's max)
    is DEAD — the slot sits in the human-driven leg exactly like a no-refresh one (the
    2026-07-18 ipazia limbo), so it must enter the sidecar and accrue age."""
    now = 5_000_000.0
    dead_refresh = sup.SlotFact(email="dr@x.com", has_refresh=True, expires_days=0.2,
                                refresh_failures=3)
    facts = {s.email: s for s in sup._track_cannot_self_renew(tmp_path, (dead_refresh,), now)}
    assert facts["dr@x.com"].cannot_self_renew_age_s == 0.0
    assert "dr@x.com" in json.loads((tmp_path / "cookie-leg-since.json").read_text())
