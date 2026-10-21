#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""OAuth-cookie refresh reminder (opt-in) — surfacing half of the OAuth-rotator
supervisor (TRDD-32acd15f).

When the local multi-account rotator is set up, this per-session detector
compares each account's claude.ai SESSION-COOKIE lifetime against its
OAuth-token lifetime and reminds the user to run /janitor-refresh-cc-logins BEFORE
a cookie expires AND while OAuth is still healthy — so the two expiries never
coincide (which would leave no working account to run the refresh from).

OPT-IN BY PRESENCE: silent no-op unless a rotator home containing a state.json
is found (CLAUDE_ROTATOR_HOME, ~/.claude/account-rotator, or
$CLAUDE_PLUGIN_DATA/oauth-rotator). It therefore NEVER fires for janitor
installs without the rotator. Read-only: reads cookie + slot metadata, never
secret values.

Logic mirrors ~/.claude/account-rotator/lifetime-status.sh (the on-demand
companion). It prints NOTHING (TRDD-1J9B7MWO): each at-risk account is recorded as an owner
remediation and the janitor daemon sends the user ONE desktop notification per episode.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))
sys.path.insert(0, str(_HERE.parent / "oauth_rotator"))

import rotator  # noqa: E402  # scripts/oauth_rotator/rotator.py (shared profiles-root resolver)
import rotator_alert  # noqa: E402  # records owner remediations; the daemon notifies (TRDD-1J9B7MWO)
import state  # noqa: E402
import supervisor  # noqa: E402  # scripts/oauth_rotator/supervisor.py (keychain-aware slot facts)

# Chrome stores expires_utc as microseconds since 1601-01-01.
_EPOCH_OFFSET_SEC = 11644473600


def _rotator_home() -> Path | None:
    """The rotator home the DAEMON uses, or None (opt-in no-op). Delegates to the SSOT
    `rotator.configured_rotator_home()` so this detector and the daemon ALWAYS read the same
    state.json — the old legacy-first resolver diverged from the daemon's canonical-first order on a
    migrated install and read stale state (TRDD-5EUYV08H)."""
    return rotator.configured_rotator_home()


def _cookie_days(profiles_root: Path, email: str, now: float) -> float | None:
    """Days until the persistent claude.ai session cookie expires, or None when the profile is
    absent or readable with no live session cookie. An existing profile that cannot be READ raises
    sqlite3.Error (not None): the caller must tell "no cookie" from "could not look" (TRDD-1J9B7MWO)."""
    db = profiles_root / f"chrome-profile-{email}" / "Default" / "Cookies"
    if not db.is_file():
        return None
    chrome_now = int((now + _EPOCH_OFFSET_SEC) * 1_000_000)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT name, expires_utc FROM cookies WHERE host_key LIKE '%claude.ai'"
        ).fetchall()
    finally:
        con.close()
    sk = [exp for (n, exp) in rows if n == "sessionKey" and exp > chrome_now]
    if sk:
        return (sk[0] / 1_000_000 - _EPOCH_OFFSET_SEC - now) / 86400.0
    persistent = [exp for (_, exp) in rows if exp > chrome_now]
    if len(persistent) >= 5:
        return (max(persistent) / 1_000_000 - _EPOCH_OFFSET_SEC - now) / 86400.0
    return None


def _oauth_map(home: Path, now: float) -> dict[str, tuple[bool, float | None]]:
    """email -> (has_refresh_token, token_expiry_days), read KEYCHAIN-FIRST.

    Delegates to supervisor._slot_facts — the SAME keychain-aware reader
    oauth-login-needed uses — instead of reading the plaintext slot files
    directly (audit §3.2). Since P4a the slot blobs live ENCRYPTED in the OS
    keychain and the plaintext files were DELETED, so the old direct read
    always returned (False, None) and made every account look unhealthy. The
    legacy plaintext file is still honoured as a fallback INSIDE _slot_facts for
    any not-yet-migrated slot, so this strictly widens what classifies as
    healthy — it never narrows it."""
    return {
        f.email: (f.has_refresh, f.expires_days)
        for f in supervisor._slot_facts(home, now)
    }


def main() -> int:
    state.init_state()

    home = _rotator_home()
    if home is None:
        return 0  # opt-in: no rotator configured on this machine → silent no-op

    # Resolve the Chrome-profiles root through the SHARED engine resolver (audit B-F2)
    # so this detector agrees with rotator/open-login.sh/the capture on a migrated
    # install. _profiles_root() honours CLAUDE_ROTATOR_PROFILES first (tests + the
    # standalone seed-login override) and ADDS the legacy ~/.claude/account-rotator
    # fallback this detector previously lacked.
    profiles_root = rotator._profiles_root()
    remind_days = state.coerce_int(os.environ.get("CLAUDE_ROTATOR_COOKIE_REMIND_DAYS"), 7)
    setup_remind_days = state.coerce_int(os.environ.get("CLAUDE_ROTATOR_SETUP_REMIND_DAYS"), 30)

    try:
        slots = json.loads((home / "state.json").read_text()).get("slots", {})
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(slots, dict) or not slots:
        return 0

    # Same opt-in gate as oauth-login-needed: a paused rotator records nothing. (_slot_facts also
    # returns () without it, but the per-account loop below would still record on defaults.)
    if not supervisor.opt_in_present(home):
        return 0

    now = time.time()
    oauth = _oauth_map(home, now)
    # Credential slots READ this pass (the keychain-aware reader skips an unreadable blob). Only a
    # read slot can show healthy OAuth.
    read_slots = [e for e in slots if e in oauth]
    unreadable_creds = len(slots) - len(read_slots)
    any_healthy_oauth = any(
        has_refresh or (days is not None and days > 1) for has_refresh, days in map(oauth.__getitem__, read_slots)
    )
    at_risk: list[tuple[str, str, str]] = []  # (email, kind, human detail)
    examined: set[str] = set()  # accounts whose credential AND cookie were read: observed
    profile_unreadable = False
    for email in slots:
        has_refresh, oauth_days = oauth.get(email, (False, None))
        try:
            cd = _cookie_days(profiles_root, email, now)
        except sqlite3.Error:
            # An I/O failure reading an existing profile = NOT observed: its record and episode
            # survive, and it blocks the machine-wide "nothing at risk" clear.
            profile_unreadable = True
            continue
        # Deliberate: an account whose credential slot is unreadable but whose cookie is at risk is still recorded, and is cleared only by an observed fine pass or the 7-day prune (rotator_alert.REMEDIATION_MAX_AGE_S).
        if email in oauth:
            examined.add(email)
        if cd is None:
            # Readable (or absent) profile with no live session cookie: observed, nothing for THIS
            # detector. "This account needs a human login" is oauth-login-needed's message, and
            # recording it here too would pop a second notification for the same account.
            continue
        if cd < remind_days:
            at_risk.append((email, "cookie", f"cookie {cd:.0f}d"))
        elif (not has_refresh) and oauth_days is not None and oauth_days < setup_remind_days:
            at_risk.append((email, "setup-token", f"setup-token {oauth_days:.0f}d"))

    # USER ruling 2026-10-21 (TRDD-1J9B7MWO): rotator and account issues NEVER reach an agent, so
    # this detector prints nothing (it used to print a daily "[oauth-cookie-refresh]" line into
    # every session). It only RECORDS one owner remediation per at-risk account; the janitor DAEMON
    # notifies the user once per episode (rotator_alert.notify_new_remediations).
    # The kind is the reason bucket and stays constant per account, so one event never flips every
    # account into a new episode (N popups). A finer day bucket (7d / 2d) is deliberately NOT
    # used: one episode per reason; urgency is the single machine-wide record below.
    for email, kind, detail in at_risk:
        rotator_alert.record_owner_remediation(
            home,
            "oauth-cookie-refresh",
            f"account {email} claude.ai login needs refresh ({detail}) - "
            "run /janitor-refresh-cc-logins "
            + ("(safe window while OAuth is healthy)" if any_healthy_oauth else "(no account has healthy OAuth)"),
            now,
            kind=kind,
            slot=email,
        )
    # OBSERVED CLEARS: only an account whose credential slot AND cookie were actually read this
    # pass and that is not at risk is observed fine; an unread one keeps its record and episode.
    rotator_alert.clear_owner_remediations(
        home, "oauth-cookie-refresh", now,
        keep_slots=frozenset(e for e, _, _ in at_risk),
        observed_slots=frozenset(examined),
    )

    # ONE machine-wide urgent record (slot "", kind "": the episode key never changes with the
    # unreadable count, which lives in the message text only).
    #  - read no credential slot at all (e.g. locked keychain): says nothing, neither records nor clears.
    #  - some account at risk and no READ slot healthy: record. An unreadable credential slot is
    #    unusable to the rotator too, so it must not block the alarm.
    #  - a read slot healthy: clear. Nothing at risk: clear only when every existing profile was
    #    read, else the at-risk account may be the unreadable one (partial-read flap).
    if read_slots:
        if at_risk and not any_healthy_oauth:
            tail = f" ({unreadable_creds} account(s) could not be read)" if unreadable_creds else ""
            rotator_alert.record_owner_remediation(
                home,
                "oauth-cookie-refresh-now",
                "claude.ai logins need refresh and no account has healthy OAuth"
                f"{tail} - run /janitor-refresh-cc-logins NOW (the login is a fresh human "
                "sign-in, so the command still works)",
                now,
            )
        elif any_healthy_oauth or not profile_unreadable:
            rotator_alert.clear_owner_remediations(home, "oauth-cookie-refresh-now", now)

    state.rotate_log_if_big("oauth-cookie-reminder")
    return 0


if __name__ == "__main__":
    sys.exit(main())
