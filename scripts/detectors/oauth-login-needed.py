#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""OAuth one-time-login nudge (opt-in) — the reactive sibling of
oauth-cookie-reminder (TRDD-32acd15f, P4c).

When the local multi-account rotator is set up, this per-session detector
surfaces the accounts that need a ONE-TIME human login because they can
neither self-renew NOR auto-bootstrap:

  * no refreshToken  → the daemon's keepalive-refresh cannot keep it alive, AND
  * no live claude.ai Chrome session → the rotator's post-login auto-bootstrap
    (slot_capture_browser, Part B) has nothing to mint a refresh token from, AND
  * the token is expired / near-expired (within a small grace window).

Those three together mean only a fresh human sign-in can revive the account.
Accounts that DO carry a refreshToken (daemon-refreshed) or DO have a live
session (bootstrap-eligible) are deliberately NOT nudged here — single
responsibility, distinct from cookie-reminder which is about the cookie/OAuth
expiry RACE.

OPT-IN BY PRESENCE: silent no-op unless a rotator home containing a state.json
is found (CLAUDE_ROTATOR_HOME, ~/.claude/account-rotator, or
$CLAUDE_PLUGIN_DATA/oauth-rotator). NOT gated on the opt-in.flag — the login
nudge helps the user finish setup even before they flip full auto-management on.
Read-only: reads cookie + slot metadata, never secret values, never launches a
browser. Machine-scoped daily dedupe keeps it to ~one nudge/day while a login is
due, even though the per-session heartbeat fires it in every project.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))
sys.path.insert(0, str(_HERE.parent / "oauth_rotator"))

import dedupe  # noqa: E402
import state  # noqa: E402
import supervisor  # noqa: E402  # scripts/oauth_rotator/supervisor.py (keychain-aware slot facts)

# Chrome stores expires_utc as microseconds since 1601-01-01.
_EPOCH_OFFSET_SEC = 11644473600


def _rotator_home() -> Path | None:
    """First rotator home that contains a state.json, or None (opt-in no-op).

    Identical resolution to oauth-cookie-reminder._rotator_home so the two
    sibling detectors agree on which home is "configured" — honours
    CLAUDE_ROTATOR_HOME (used by the standalone seed-login setup + the tests),
    then ~/.claude/account-rotator, then $CLAUDE_PLUGIN_DATA/oauth-rotator."""
    candidates: list[Path] = []
    env_home = os.environ.get("CLAUDE_ROTATOR_HOME", "").strip()
    if env_home:
        candidates.append(Path(env_home))
    candidates.append(Path.home() / ".claude" / "account-rotator")
    data = os.environ.get("CLAUDE_PLUGIN_DATA", "").strip()
    if data:
        candidates.append(Path(data) / "oauth-rotator")
    for c in candidates:
        if (c / "state.json").is_file():
            return c
    return None


def slot_needs_login(
    has_refresh: bool,
    token_days: float | None,
    has_session_key: bool,
    grace_days: float,
) -> bool:
    """PURE: does this account need a ONE-TIME human login?

    Needs a human login iff it can't self-renew AND has no seeded session to
    auto-bootstrap from AND its token is expired / near-expired.
    """
    if has_refresh:        # daemon refreshes it via the refresh grant -> no nudge
        return False
    if has_session_key:    # bootstrap-eligible (Part B) -> no LOGIN nudge
        return False
    return token_days is None or token_days <= grace_days


def _cookie_days(profiles_root: Path, email: str, now: float) -> float | None:
    """Days until the persistent claude.ai session cookie expires, or None.

    Mirrors oauth-cookie-reminder._cookie_days (the canonical reader). Opens the
    account's Chrome Cookies sqlite read-only; returns None when there is no live
    sessionKey, which is exactly the "no seeded session" signal the login nudge
    keys off."""
    db = profiles_root / f"chrome-profile-{email}" / "Default" / "Cookies"
    if not db.is_file():
        return None
    chrome_now = int((now + _EPOCH_OFFSET_SEC) * 1_000_000)
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = con.execute(
            "SELECT name, expires_utc FROM cookies WHERE host_key LIKE '%claude.ai'"
        ).fetchall()
        con.close()
    except sqlite3.Error:
        return None
    sk = [exp for (n, exp) in rows if n == "sessionKey" and exp > chrome_now]
    if sk:
        return (sk[0] / 1_000_000 - _EPOCH_OFFSET_SEC - now) / 86400.0
    persistent = [exp for (_, exp) in rows if exp > chrome_now]
    if len(persistent) >= 5:
        return (max(persistent) / 1_000_000 - _EPOCH_OFFSET_SEC - now) / 86400.0
    return None


def _has_live_session(profiles_root: Path, email: str, now: float) -> bool:
    """True iff a live (not-yet-expired) claude.ai session cookie exists for the
    account — i.e. the post-login auto-bootstrap could mint a refresh token from it."""
    cd = _cookie_days(profiles_root, email, now)
    return cd is not None and cd > 0


def _grace_days() -> float:
    """Login-nudge grace window (days). Env-overridable; default 1.0.

    A bad value (non-numeric / non-positive) falls back to the default so a typo
    in the env never crashes the heartbeat or disables the nudge silently."""
    raw = os.environ.get("CLAUDE_ROTATOR_LOGIN_NUDGE_GRACE_DAYS", "").strip()
    if not raw:
        return 1.0
    try:
        val = float(raw)
    except ValueError:
        return 1.0
    return val if val > 0 else 1.0


def main() -> int:
    state.init_state()

    home = _rotator_home()
    if home is None:
        return 0  # opt-in: no rotator configured on this machine -> silent no-op

    profiles_root = Path(
        os.environ.get("CLAUDE_ROTATOR_PROFILES", "").strip() or str(home / "profiles")
    )
    grace = _grace_days()
    now = time.time()

    # supervisor._slot_facts is keychain-aware (reads each slot's token blob from
    # the OS keychain, plaintext-file fallback) and returns only NON-secret
    # metadata: (email, has_refresh, expires_days). Exactly what the classifier needs.
    facts = supervisor._slot_facts(home, now)
    if not facts:
        state.rotate_log_if_big("oauth-login-needed")
        return 0

    needing: list[str] = []
    for f in facts:
        has_session = _has_live_session(profiles_root, f.email, now)
        if slot_needs_login(f.has_refresh, f.expires_days, has_session, grace):
            needing.append(f.email)

    if not needing:
        state.rotate_log_if_big("oauth-login-needed")
        return 0

    needing = sorted(needing)
    # Machine-scoped daily dedupe — the rotator is machine-wide, not per-project,
    # so one nudge/day regardless of how many projects/sessions fire heartbeats.
    seen = home / ".oauth-login-needed-seen.txt"
    sig = hashlib.sha1(",".join(needing).encode("utf-8")).hexdigest()[:8]
    key = f"due-{int(now // 86400)}-{sig}"
    emails = ", ".join(needing)
    msg = (
        f"[oauth-login-needed] {len(needing)} account(s) need a one-time login: "
        f"{emails} — run `~/.claude/account-rotator/open-login.sh <email>` for each "
        f"(opens a DEDICATED Chrome window; your default browser is untouched). "
        f"The rotator auto-bootstraps the rest."
    )
    line = dedupe.emit_once(seen, key, msg)
    if line is not None:
        print(line)

    state.rotate_log_if_big("oauth-login-needed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
