"""The OAuth-rotator cascade — ONE paradigm in three parts, each falling back to
the next when it can't act: **ROTATE → RENEW → REAUTHENTICATE** (TRDD-dfc0959a).

This module is the SINGLE SOURCE OF TRUTH for the per-account cascade
classification. Both the global daemon (``rotator.cmd_tick``) and the heartbeat
nudge detectors (``oauth-login-needed`` / ``oauth-cookie-reminder``) import
``classify`` so they can NEVER disagree about whether an account self-renews,
can be renewed behind the scenes, or genuinely needs a human re-login.

The three cascade layers (USER's authoritative design):

1. **ROTATE** — swap Claude Code's live keychain credential to the next stored
   OAuth token when the live account hits a usage limit / expires. Real-time,
   silent, agents never notice. This leg is usage-driven and lives in
   ``rotator.cmd_auto`` (it needs the /api/oauth/usage probe); the cascade does
   NOT re-implement it. The cascade's job is the *fallback* legs below, applied
   to the ALTERNATE slots so a healthy account always exists to rotate TO.

2. **RENEW** (fallback when there is nothing healthy to rotate to / a slot is
   expiring) — bring a degraded slot back, behind the scenes:
   - ``RENEW_REFRESH``: the slot carries a refresh token and is within
     ``keepalive_ahead_h`` of expiry → ``rotator._keepalive_refresh`` exchanges
     it for a fresh token (silent HTTP, no browser).
   - ``RENEW_COOKIE``: the slot has NO refresh token but DOES have a live
     claude.ai session cookie → ``rotator._bootstrap_seeded_slots`` launches the
     CDP-attach capture to mint a fresh refresh-bearing slot from that session.

3. **REAUTHENTICATE** (fallback when RENEW can't — no refresh AND no live cookie,
   and the token is dead/near-dead) — the ONLY human step: the janitor NUDGES the
   user to re-login (``/refresh-claude-logins``). ~Monthly. This is the
   ``REAUTH_NUDGE`` leg the detectors surface.

``WAIT_SETUP_TOKEN`` is the benign in-between: a setup-token slot (no refresh, no
session) that still has runway — nothing to do yet, do NOT nudge.

The module is a pure LEAF (stdlib only, no ``rotator`` import → no import cycle).
Thresholds are passed in by the caller (rotator's ``KEEPALIVE_AHEAD_H`` and the
detector's login grace) so the defaults here stay advisory, never a second
source of truth for the constants.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Advisory defaults — mirror the env defaults in rotator.py (KEEPALIVE_AHEAD_H=2)
# and oauth-login-needed._grace_days (1.0). Callers pass the live values; these
# only matter when classify is used standalone (e.g. a unit test).
DEFAULT_KEEPALIVE_AHEAD_H = 2.0
DEFAULT_LOGIN_GRACE_DAYS = 1.0


class CascadeLeg(str, Enum):
    """Which leg of the ROTATE→RENEW→REAUTH cascade an ALTERNATE account sits in.

    (The live account is ROTATE's concern, not this classification's — see
    ``classify``.) ``str`` mixin so a leg is JSON/log friendly.
    """

    HEALTHY = "healthy"                 # has refresh, ample runway — self-renews; no action
    RENEW_REFRESH = "renew_refresh"     # has refresh, near expiry — keepalive refreshes it
    RENEW_COOKIE = "renew_cookie"       # no refresh, live session — bootstrap mints a refresh slot
    REAUTH_NUDGE = "reauth_nudge"       # no refresh, no session, dead/near — human must re-login
    WAIT_SETUP_TOKEN = "wait_setup_token"  # no refresh, no session, still has runway — nothing yet


@dataclass(frozen=True)
class AccountState:
    """The cascade-relevant facts about ONE account — all non-secret metadata.

    ``token_expires_h`` is hours until the OAuth token's local ``expiresAt``
    (``None`` when undatable). ``has_session_cookie`` is whether a live claude.ai
    ``sessionKey`` cookie exists for the account's seeded Chrome profile
    (``rotator._profile_has_session_key``).
    """

    email: str
    is_live: bool
    has_refresh: bool
    token_expires_h: float | None
    has_session_cookie: bool


def classify(
    acct: AccountState,
    *,
    keepalive_ahead_h: float = DEFAULT_KEEPALIVE_AHEAD_H,
    login_grace_days: float = DEFAULT_LOGIN_GRACE_DAYS,
) -> CascadeLeg:
    """Classify ONE account into its cascade leg. The SSOT both daemon + detectors use.

    The LIVE account is owned by Claude Code (it refreshes its own rotating grant)
    and, when exhausted, is handled by the ROTATE leg (``cmd_auto``) — NOT by the
    RENEW/REAUTH legs here. So a live account always classifies ``HEALTHY`` from
    this function's POV; the rotator never renews or nudges-reauth for it. This
    mirrors ``_keepalive_refresh`` skipping ``email == live_email``.

    For an ALTERNATE (non-live) slot the rules below match the existing primitives
    exactly:
    - ``RENEW_REFRESH`` ⇔ ``_keepalive_refresh`` eligibility (has refresh, datable,
      within ``keepalive_ahead_h`` of expiry).
    - ``RENEW_COOKIE`` ⇔ ``rotator._bootstrap_eligible`` / the detector's
      ``slot_capture_stalled`` (``not has_refresh and has_session_cookie``).
    - ``REAUTH_NUDGE`` ⇔ the detector's ``slot_needs_login`` (no refresh, no
      session, token ``None``/within ``login_grace_days``).
    """
    if acct.is_live:
        return CascadeLeg.HEALTHY

    if acct.has_refresh:
        # Datable AND within the keepalive window → the daemon will refresh it.
        if acct.token_expires_h is not None and acct.token_expires_h <= keepalive_ahead_h:
            return CascadeLeg.RENEW_REFRESH
        return CascadeLeg.HEALTHY

    # No refresh token from here down.
    if acct.has_session_cookie:
        # A live seeded session exists → the cookie-capture can mint a refresh slot.
        return CascadeLeg.RENEW_COOKIE

    # No refresh AND no live session: the only fix is a human re-login — but only
    # once the setup-token is actually dead/near-dead. A setup-token with runway is
    # benign (WAIT) and must NOT be nudged.
    token_days = (acct.token_expires_h / 24.0) if acct.token_expires_h is not None else None
    if token_days is None or token_days <= login_grace_days:
        return CascadeLeg.REAUTH_NUDGE
    return CascadeLeg.WAIT_SETUP_TOKEN


@dataclass(frozen=True)
class CascadePlan:
    """The fleet-level RENEW/REAUTH buckets, in cascade order. ROTATE is reported
    separately by the caller (``cmd_auto``) since it is usage-driven; this plan
    captures the *fallback* legs the cascade owns, so the daemon can log ONE
    explicit cascade line and the detectors can nudge from the same buckets.
    """

    renew_refresh: tuple[str, ...]
    renew_cookie: tuple[str, ...]
    reauth_nudge: tuple[str, ...]
    waiting: tuple[str, ...]
    healthy: tuple[str, ...]

    def summary_line(self) -> str:
        """A compact, log-friendly one-liner naming the non-empty fallback legs."""
        parts: list[str] = []
        if self.renew_refresh:
            parts.append("renew-refresh=%s" % ",".join(self.renew_refresh))
        if self.renew_cookie:
            parts.append("renew-cookie=%s" % ",".join(self.renew_cookie))
        if self.reauth_nudge:
            parts.append("reauth-nudge=%s" % ",".join(self.reauth_nudge))
        if self.waiting:
            parts.append("waiting=%s" % ",".join(self.waiting))
        return "cascade: " + (" ".join(parts) if parts else "all alternates healthy")


def cascade_plan(
    accounts: list[AccountState],
    *,
    keepalive_ahead_h: float = DEFAULT_KEEPALIVE_AHEAD_H,
    login_grace_days: float = DEFAULT_LOGIN_GRACE_DAYS,
) -> CascadePlan:
    """Classify every account and bucket the ALTERNATES into the cascade's fallback
    legs (sorted, stable). Live accounts land in ``healthy`` (see ``classify``)."""
    buckets: dict[CascadeLeg, list[str]] = {leg: [] for leg in CascadeLeg}
    for acct in accounts:
        leg = classify(
            acct,
            keepalive_ahead_h=keepalive_ahead_h,
            login_grace_days=login_grace_days,
        )
        buckets[leg].append(acct.email)
    return CascadePlan(
        renew_refresh=tuple(sorted(buckets[CascadeLeg.RENEW_REFRESH])),
        renew_cookie=tuple(sorted(buckets[CascadeLeg.RENEW_COOKIE])),
        reauth_nudge=tuple(sorted(buckets[CascadeLeg.REAUTH_NUDGE])),
        waiting=tuple(sorted(buckets[CascadeLeg.WAIT_SETUP_TOKEN])),
        healthy=tuple(sorted(buckets[CascadeLeg.HEALTHY])),
    )
