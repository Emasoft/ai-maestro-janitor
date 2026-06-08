"""Tests for the OAuth-rotator cascade SSOT (scripts/oauth_rotator/cascade.py).

Two layers, both real (no mocks):
  * classify() truth table — every cascade leg + the boundary conditions.
  * SSOT-equivalence — classify() reproduces the EXISTING primitives byte-for-byte
    (rotator._bootstrap_eligible and the detector truth tables) so the Phase-1
    delegation cannot change behavior. If these fail, the delegation is unsafe.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scripts" / "oauth_rotator"))

import cascade  # noqa: E402
import rotator  # noqa: E402  # for the _bootstrap_eligible equivalence proof

KA = 2.0   # keepalive_ahead_h (hours) — rotator.KEEPALIVE_AHEAD_H default
GRACE = 1.0  # login_grace_days — oauth-login-needed._grace_days default


def _acct(*, is_live=False, has_refresh=False, token_h=None, session=False):
    return cascade.AccountState(
        email="a@x.com",
        is_live=is_live,
        has_refresh=has_refresh,
        token_expires_h=token_h,
        has_session_cookie=session,
    )


def _c(acct):
    return cascade.classify(acct, keepalive_ahead_h=KA, login_grace_days=GRACE)


# ---------------------------------------------------------------------------
# classify() truth table
# ---------------------------------------------------------------------------
def test_live_account_is_always_healthy() -> None:
    """The live account is ROTATE's concern (cmd_auto), never RENEW/REAUTH — HEALTHY."""
    assert _c(_acct(is_live=True, has_refresh=False, token_h=None, session=False)) is cascade.CascadeLeg.HEALTHY
    assert _c(_acct(is_live=True, has_refresh=True, token_h=0.1, session=False)) is cascade.CascadeLeg.HEALTHY


def test_has_refresh_ample_runway_healthy() -> None:
    """A refresh-capable slot with runway beyond the keepalive window self-renews → HEALTHY."""
    assert _c(_acct(has_refresh=True, token_h=10.0)) is cascade.CascadeLeg.HEALTHY


def test_has_refresh_near_expiry_renew_refresh() -> None:
    """A refresh-capable slot within keepalive_ahead_h of expiry → keepalive refreshes it."""
    assert _c(_acct(has_refresh=True, token_h=1.0)) is cascade.CascadeLeg.RENEW_REFRESH


def test_keepalive_boundary_is_inclusive() -> None:
    """token_expires_h exactly == keepalive_ahead_h is within the window (<=) → RENEW_REFRESH."""
    assert _c(_acct(has_refresh=True, token_h=2.0)) is cascade.CascadeLeg.RENEW_REFRESH


def test_has_refresh_undatable_is_healthy() -> None:
    """An undatable (None) refresh-capable slot is left alone (keepalive skips None) → HEALTHY."""
    assert _c(_acct(has_refresh=True, token_h=None)) is cascade.CascadeLeg.HEALTHY


def test_no_refresh_with_session_is_renew_cookie() -> None:
    """No refresh but a live claude.ai session → bootstrap can mint a refresh slot (RENEW_COOKIE)."""
    assert _c(_acct(has_refresh=False, session=True, token_h=-5.0)) is cascade.CascadeLeg.RENEW_COOKIE
    assert _c(_acct(has_refresh=False, session=True, token_h=999.0)) is cascade.CascadeLeg.RENEW_COOKIE


def test_no_refresh_no_session_dead_token_is_reauth() -> None:
    """No refresh, no session, token undatable/expired/near → the human must re-login."""
    assert _c(_acct(has_refresh=False, session=False, token_h=None)) is cascade.CascadeLeg.REAUTH_NUDGE
    assert _c(_acct(has_refresh=False, session=False, token_h=-48.0)) is cascade.CascadeLeg.REAUTH_NUDGE


def test_reauth_grace_boundary_is_inclusive() -> None:
    """token exactly == login_grace_days (1.0 d == 24 h) is at/within grace → REAUTH_NUDGE."""
    assert _c(_acct(has_refresh=False, session=False, token_h=24.0)) is cascade.CascadeLeg.REAUTH_NUDGE


def test_no_refresh_no_session_with_runway_waits() -> None:
    """A setup-token (no refresh, no session) still well within its ~1y life → WAIT, do NOT nudge."""
    assert _c(_acct(has_refresh=False, session=False, token_h=240.0)) is cascade.CascadeLeg.WAIT_SETUP_TOKEN


# ---------------------------------------------------------------------------
# cascade_plan() bucketing
# ---------------------------------------------------------------------------
def test_cascade_plan_buckets_and_sorts() -> None:
    """cascade_plan classifies a fleet, buckets per leg, and sorts each bucket."""
    fleet = [
        cascade.AccountState("z@x.com", False, True, 50.0, False),    # HEALTHY
        cascade.AccountState("a@x.com", False, True, 1.0, False),     # RENEW_REFRESH
        cascade.AccountState("c@x.com", False, False, -1.0, True),    # RENEW_COOKIE
        cascade.AccountState("b@x.com", False, False, None, False),   # REAUTH_NUDGE
        cascade.AccountState("d@x.com", False, False, 999.0, False),  # WAIT
        cascade.AccountState("live@x.com", True, False, None, False), # HEALTHY (live)
    ]
    plan = cascade.cascade_plan(fleet, keepalive_ahead_h=KA, login_grace_days=GRACE)
    assert plan.renew_refresh == ("a@x.com",)
    assert plan.renew_cookie == ("c@x.com",)
    assert plan.reauth_nudge == ("b@x.com",)
    assert plan.waiting == ("d@x.com",)
    assert plan.healthy == ("live@x.com", "z@x.com")  # sorted


def test_cascade_plan_summary_line_names_active_legs() -> None:
    """summary_line lists only the non-empty fallback legs; all-healthy says so."""
    fleet = [
        cascade.AccountState("a@x.com", False, False, None, False),   # REAUTH_NUDGE
        cascade.AccountState("c@x.com", False, False, -1.0, True),    # RENEW_COOKIE
    ]
    line = cascade.cascade_plan(fleet, keepalive_ahead_h=KA, login_grace_days=GRACE).summary_line()
    assert "reauth-nudge=a@x.com" in line
    assert "renew-cookie=c@x.com" in line
    assert "renew-refresh" not in line  # empty leg omitted

    empty = cascade.cascade_plan([], keepalive_ahead_h=KA, login_grace_days=GRACE).summary_line()
    assert empty == "cascade: all alternates healthy"


# ---------------------------------------------------------------------------
# SSOT-equivalence — classify reproduces the existing primitives EXACTLY.
# These guard the Phase-1 delegation: if classify ever diverges, this fails.
# ---------------------------------------------------------------------------
def test_renew_cookie_matches_bootstrap_eligible() -> None:
    """(classify == RENEW_COOKIE) is byte-identical to rotator._bootstrap_eligible for
    all (has_refresh, has_session) combos — so delegating _bootstrap_eligible is safe."""
    for has_refresh in (False, True):
        for has_session in (False, True):
            acct = _acct(has_refresh=has_refresh, session=has_session, token_h=-5.0)
            via_cascade = _c(acct) is cascade.CascadeLeg.RENEW_COOKIE
            assert via_cascade == rotator._bootstrap_eligible(has_refresh, has_session), (
                f"divergence at has_refresh={has_refresh} has_session={has_session}"
            )


def _slot_needs_login_ref(has_refresh, token_days, has_session, grace):
    """The detector's slot_needs_login logic, replicated as the reference truth table."""
    if has_refresh:
        return False
    if has_session:
        return False
    return token_days is None or token_days <= grace


def test_reauth_nudge_matches_slot_needs_login() -> None:
    """(classify == REAUTH_NUDGE) reproduces the detector's slot_needs_login across the grid."""
    for has_refresh in (False, True):
        for has_session in (False, True):
            for token_days in (None, -2.0, 0.5, 1.0, 10.0):
                token_h = None if token_days is None else token_days * 24.0
                acct = _acct(has_refresh=has_refresh, session=has_session, token_h=token_h)
                via_cascade = _c(acct) is cascade.CascadeLeg.REAUTH_NUDGE
                ref = _slot_needs_login_ref(has_refresh, token_days, has_session, GRACE)
                assert via_cascade == ref, (
                    f"divergence at refresh={has_refresh} session={has_session} days={token_days}"
                )


def test_renew_cookie_matches_slot_capture_stalled() -> None:
    """(classify == RENEW_COOKIE) reproduces the detector's slot_capture_stalled
    ((not has_refresh) and has_session) across the grid."""
    for has_refresh in (False, True):
        for has_session in (False, True):
            acct = _acct(has_refresh=has_refresh, session=has_session, token_h=-5.0)
            via_cascade = _c(acct) is cascade.CascadeLeg.RENEW_COOKIE
            ref = (not has_refresh) and has_session
            assert via_cascade == ref


# ---------------------------------------------------------------------------
# rotator._build_fleet_state — the daemon's per-beat cascade snapshot.
# ---------------------------------------------------------------------------
def test_build_fleet_state_maps_keychain_and_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    """_build_fleet_state snapshots each account's has_refresh/expiry (keychain) +
    has_session_cookie (seeded profile) into AccountState, marks the live one, and the
    resulting plan classifies them through the SSOT exactly as expected."""
    now = time.time()
    state = {"live_email": "live@x.com",
             "slots": {"live@x.com": {}, "alt@x.com": {}, "dead@x.com": {}}}
    slots = {
        "live@x.com": {"claudeAiOauth": {"refreshToken": "r",
                                         "expiresAt": int((now + 100 * 3600) * 1000)}},
        "alt@x.com": {"claudeAiOauth": {"refreshToken": "r2",
                                        "expiresAt": int((now + 1 * 3600) * 1000)}},  # near expiry
        "dead@x.com": {"claudeAiOauth": {"expiresAt": int((now - 3600) * 1000)}},     # no refresh, expired
    }
    monkeypatch.setattr(rotator, "read_slot", lambda e: slots.get(e))
    monkeypatch.setattr(rotator, "read_live_blob", lambda: slots["live@x.com"])
    # dead@x.com has a live seeded session (→ RENEW_COOKIE); the others do not.
    monkeypatch.setattr(rotator, "_profile_has_session_key", lambda e, now=None: e == "dead@x.com")

    fleet = {a.email: a for a in rotator._build_fleet_state(state, now)}
    assert fleet["live@x.com"].is_live and fleet["live@x.com"].has_refresh
    assert fleet["alt@x.com"].has_refresh and not fleet["alt@x.com"].is_live
    assert not fleet["dead@x.com"].has_refresh and fleet["dead@x.com"].has_session_cookie

    plan = cascade.cascade_plan(list(fleet.values()), keepalive_ahead_h=KA, login_grace_days=GRACE)
    assert plan.renew_refresh == ("alt@x.com",)   # has refresh, 1h within the 2h keepalive window
    assert plan.renew_cookie == ("dead@x.com",)   # no refresh, live session → cookie-mint
    assert "live@x.com" in plan.healthy            # live account is ROTATE's concern, not RENEW/REAUTH


def test_log_cascade_plan_writes_to_isolated_log_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REGRESSION GUARD (TRDD-dfc0959a): _log_cascade_plan is the SINGLE keychain/state/log IO
    point for the daemon's per-beat cascade visibility. Run the REAL fn against an isolated
    LOG_FILE + stubbed keychain reads and assert the cascade line lands in the TMP log — proving
    it is fully isolatable. (A cmd_tick unit test that forgets to stub _log_cascade_plan would
    otherwise leak real-account cascade lines into the production rotator.log, the exact bug this
    guards.)"""
    now = time.time()
    monkeypatch.setattr(rotator, "LOG_FILE", tmp_path / "rotator.log")
    monkeypatch.setattr(rotator, "load_state",
                        lambda: {"live_email": "live@x.com",
                                 "slots": {"live@x.com": {}, "dead@x.com": {}}})
    monkeypatch.setattr(rotator, "read_slot",
                        lambda e: {"claudeAiOauth": {"refreshToken": "r",
                                                     "expiresAt": int((now + 100 * 3600) * 1000)}}
                        if e == "live@x.com"
                        else {"claudeAiOauth": {"expiresAt": int((now - 3600) * 1000)}})
    monkeypatch.setattr(rotator, "read_live_blob",
                        lambda: {"claudeAiOauth": {"refreshToken": "r",
                                                   "expiresAt": int((now + 100 * 3600) * 1000)}})
    monkeypatch.setattr(rotator, "_profile_has_session_key", lambda e, now=None: e == "dead@x.com")

    rotator._log_cascade_plan()  # the REAL fn — must not raise, must write only to the tmp log

    written = (tmp_path / "rotator.log").read_text(encoding="utf-8")
    assert "cascade:" in written
    assert "renew-cookie=dead@x.com" in written  # dead@x.com → cookie-mint leg, proven end-to-end
