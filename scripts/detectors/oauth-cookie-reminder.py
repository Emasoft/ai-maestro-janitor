#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""OAuth-cookie refresh reminder (opt-in) — surfacing half of the OAuth-rotator
supervisor (TRDD-32acd15f).

When the local multi-account rotator is set up, this per-session detector
compares each account's claude.ai SESSION-COOKIE lifetime against its
OAuth-token lifetime and reminds the user to run /refresh-claude-logins BEFORE
a cookie expires AND while OAuth is still healthy — so the two expiries never
coincide (which would leave no working account to run the refresh from).

OPT-IN BY PRESENCE: silent no-op unless a rotator home containing a state.json
is found (CLAUDE_ROTATOR_HOME, ~/.claude/account-rotator, or
$CLAUDE_PLUGIN_DATA/oauth-rotator). It therefore NEVER fires for janitor
installs without the rotator. Read-only: reads cookie + slot metadata, never
secret values.

Logic mirrors ~/.claude/account-rotator/lifetime-status.sh (the on-demand
companion). Machine-scoped daily dedupe keeps it to ~one reminder/day while a
refresh is due, even though the per-session heartbeat fires it in every project.
"""

from __future__ import annotations

import hashlib
import json
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
    """First rotator home that contains a state.json, or None (opt-in no-op)."""
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


def _cookie_days(profiles_root: Path, email: str, now: float) -> float | None:
    """Days until the persistent claude.ai session cookie expires, or None."""
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

    profiles_root = Path(
        os.environ.get("CLAUDE_ROTATOR_PROFILES", "").strip() or str(home / "profiles")
    )
    remind_days = state.coerce_int(os.environ.get("CLAUDE_ROTATOR_COOKIE_REMIND_DAYS"), 7)
    setup_remind_days = state.coerce_int(os.environ.get("CLAUDE_ROTATOR_SETUP_REMIND_DAYS"), 30)

    try:
        slots = json.loads((home / "state.json").read_text()).get("slots", {})
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(slots, dict) or not slots:
        return 0

    now = time.time()
    # Read every slot's OAuth facts ONCE, keychain-first (audit §3.2). The map is
    # keyed by email; an account with no resolvable slot blob (neither keychain nor
    # legacy file) defaults to (False, None) — same "unhealthy/login-needed" signal
    # the old per-file reader produced for a missing file.
    oauth = _oauth_map(home, now)
    at_risk: list[str] = []
    any_healthy_oauth = False
    for email in slots:
        has_refresh, oauth_days = oauth.get(email, (False, None))
        if has_refresh or (oauth_days is not None and oauth_days > 1):
            any_healthy_oauth = True
        cd = _cookie_days(profiles_root, email, now)
        if cd is None:
            at_risk.append(f"{email} (login needed)")
        elif cd < remind_days:
            at_risk.append(f"{email} (cookie {cd:.0f}d)")
        elif (not has_refresh) and oauth_days is not None and oauth_days < setup_remind_days:
            at_risk.append(f"{email} (setup-token {oauth_days:.0f}d)")

    if not at_risk:
        state.rotate_log_if_big("oauth-cookie-reminder")
        return 0

    # Machine-scoped daily dedupe — the rotator is machine-wide, not per-project,
    # so one reminder/day regardless of how many projects/sessions fire heartbeats.
    seen = home / ".oauth-cookie-reminder-seen.txt"
    sig = hashlib.sha1(
        ",".join(sorted(a.split(" ", 1)[0] for a in at_risk)).encode("utf-8")
    ).hexdigest()[:8]
    key = f"due-{int(now // 86400)}-{sig}"
    tail = (
        " — run /refresh-claude-logins while OAuth is healthy (safe window)."
        if any_healthy_oauth
        else " — run /refresh-claude-logins NOW (no account has healthy OAuth; the login is a "
        "fresh human sign-in, so the command still works)."
    )
    msg = (
        f"[oauth-cookie-refresh] {len(at_risk)} claude.ai login(s) need refresh: "
        f"{', '.join(at_risk)}{tail}"
    )
    line = dedupe.emit_once(seen, key, msg)
    if line is not None:
        print(line)

    state.rotate_log_if_big("oauth-cookie-reminder")
    return 0


if __name__ == "__main__":
    sys.exit(main())
