#!/usr/bin/env bash
# lifetime-status.sh — for EVERY rotator account, compare the claude.ai COOKIE
# (session) lifetime against the OAuth-token lifetime and decide whether a login
# refresh is due. The whole point: remind you to run /janitor-refresh-cc-logins
# BEFORE the cookie expires AND while OAuth is still healthy, so the two expiries
# never coincide (a coincidence would leave no working account to run the
# command from). Read-only — reads cookie metadata + slot/token metadata, never
# secret values.
set -uo pipefail
ROT="${CLAUDE_ROTATOR_HOME:-${CLAUDE_PLUGIN_DATA:-$HOME/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins}/oauth-rotator}"

# Resolve the rotator engine as our IN-PLUGIN SIBLING (TRDD-3T4DZWXA — ported into the
# plugin; was a cache glob), overridable for tests/dev via CLAUDE_ROTATOR_PY. We only
# ever call its read-only subcommands (print-profiles-root / oauth-health); if either is
# unavailable we fall back — see below — so this monitor degrades, never breaks.
ROTATOR_PY="${CLAUDE_ROTATOR_PY:-$(cd "$(dirname "$0")" && pwd)/rotator.py}"

# Profiles root via the SHARED engine resolver (audit H1) so this monitor agrees
# with rotator / open-login.sh / the capture on a migrated install. Honour an
# explicit CLAUDE_ROTATOR_PROFILES first; else ask the engine; else fall back to
# the legacy default.
PROFILE_ROOT="${CLAUDE_ROTATOR_PROFILES:-}"
if [ -z "$PROFILE_ROOT" ] && [ -n "$ROTATOR_PY" ]; then
  # Only accept an ABSOLUTE path. An OLDER cached rotator that predates this
  # subcommand prints "unknown command: print-profiles-root" to STDOUT (not
  # stderr), so a bare command-substitution would poison PROFILE_ROOT with that
  # text. The /*) guard rejects the garbage and we fall back to the legacy dir.
  _pr="$(python3 "$ROTATOR_PY" print-profiles-root 2>/dev/null || true)"
  case "$_pr" in /*) PROFILE_ROOT="$_pr" ;; esac
fi
[ -n "$PROFILE_ROOT" ] || PROFILE_ROOT="$ROT/profiles"

# OAuth health from the KEYCHAIN via the engine (audit C2) — NOT the plaintext
# slots/*.json the keychain migration DELETES (reading those made every account
# look unhealthy and printed a false "no healthy OAuth" banner on every migrated
# machine). Empty string when the engine or its oauth-health subcommand is
# unavailable; the Python below then treats OAuth health as UNKNOWN (never as
# unhealthy).
OAUTH_HEALTH_JSON=""
if [ -n "$ROTATOR_PY" ]; then
  # Same STDOUT-garbage guard: an older rotator prints "unknown command:
  # oauth-health". Only keep the output when it actually looks like a JSON object
  # ({...}); otherwise leave it empty so the Python below treats health as UNKNOWN.
  _oh="$(python3 "$ROTATOR_PY" oauth-health --json 2>/dev/null || true)"
  case "$_oh" in "{"*) OAUTH_HEALTH_JSON="$_oh" ;; esac
fi

REMIND_DAYS="${CLAUDE_ROTATOR_COOKIE_REMIND_DAYS:-7}"       # remind this long before cookie expiry
SETUP_REMIND_DAYS="${CLAUDE_ROTATOR_SETUP_REMIND_DAYS:-30}" # re-capture setup-tokens this long before their ~1y expiry

python3 - "$ROT" "$PROFILE_ROOT" "$REMIND_DAYS" "$SETUP_REMIND_DAYS" "$OAUTH_HEALTH_JSON" <<'PY'
import json, os, sqlite3, sys, time
rot, prof_root, remind_days, setup_remind_days = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
oauth_health_json = sys.argv[5] if len(sys.argv) > 5 else ""
now = time.time()
chrome_now = int((now + 11644473600) * 1_000_000)

# Keychain OAuth health from the engine (audit C2). {} when the engine could not
# answer → health is UNKNOWN, which is explicitly NOT the same as "unhealthy".
oauth_health = {}
if oauth_health_json:
    try:
        oauth_health = json.loads(oauth_health_json)
    except Exception:
        oauth_health = {}
health_known = bool(oauth_health)

# Roster: the engine's reported accounts (keychain SSOT) unioned with the
# state.json slots index. state.json is still a valid roster post-migration even
# though it no longer carries the token blobs.
try:
    slots = json.load(open(os.path.join(rot, "state.json"))).get("slots", {})
except Exception:
    slots = {}
roster = list(dict.fromkeys(list(oauth_health.keys()) + list(slots.keys())))
if not roster:
    print("No accounts configured in the rotator."); sys.exit(1)

def cookie_days(email):
    """Days until the claude.ai session cookie expires, or None if no live session."""
    db = os.path.join(prof_root, f"chrome-profile-{email}", "Default", "Cookies")
    if not os.path.exists(db):
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = con.execute("SELECT name, expires_utc FROM cookies WHERE host_key LIKE '%claude.ai'").fetchall()
        con.close()
    except sqlite3.Error:
        return None
    sk = [exp for (n, exp) in rows if n == "sessionKey" and exp > chrome_now]
    if sk:
        return (sk[0] / 1_000_000 - 11644473600 - now) / 86400.0
    persistent = [exp for (n, exp) in rows if exp > chrome_now]
    if len(persistent) >= 5:
        return (max(persistent) / 1_000_000 - 11644473600 - now) / 86400.0
    return None

def oauth_info(email):
    """(has_refresh, token_expiry_days, status) from the engine's keychain health (audit C2).
    Returns (None, None, None) when the engine did not report this account → UNKNOWN.
    `status` is the janitor #82 per-account read state ("ok" | "latched" | "no-oauth");
    absent from an OLDER engine's JSON → None (falls through to the pre-#82 behaviour)."""
    h = oauth_health.get(email)
    if not isinstance(h, dict):
        return (None, None, None)
    return (bool(h.get("has_refresh")), h.get("expires_days"), h.get("status"))

action, oauth_cache, latched = [], {}, []
print(f"{'account':40} {'cookie/session':>16} {'oauth':>26}  verdict")
print("-" * 112)
for email in roster:
    cd = cookie_days(email)
    has_refresh, oauth_days, oauth_status = oauth_info(email)
    oauth_cache[email] = (has_refresh, oauth_days)
    if oauth_status == "latched":
        latched.append(email)
    cookie_s = "none/expired" if cd is None else f"{cd:6.1f} d"
    if has_refresh:
        oauth_s = "refresh-capable (auto)"
    elif oauth_days is not None:
        oauth_s = f"setup-token {oauth_days:5.0f} d"
    elif oauth_status == "latched":
        # janitor #82 fix #1: the keychain denied-latch is set → this account's OAuth state
        # is UNKNOWN, NOT proof it has none. "no oauth" here was alarming and wrong.
        oauth_s = "latched"
    elif not health_known:
        oauth_s = "unknown (engine n/a)"
    else:
        oauth_s = "no oauth"
    if cd is None:
        v = "LOGIN NEEDED (no live session)"; action.append(email)
    elif cd < remind_days:
        v = f"REFRESH SOON (< {remind_days}d)"; action.append(email)
    elif (not has_refresh) and oauth_days is not None and oauth_days < setup_remind_days:
        v = f"RE-CAPTURE (setup-token < {setup_remind_days}d)"; action.append(email)
    else:
        v = "ok"
    print(f"{email:40} {cookie_s:>16} {oauth_s:>26}  {v}")

print("-" * 112)
if action:
    print(f"\nACTION DUE → run  /janitor-refresh-cc-logins   (accounts: {', '.join(sorted(set(action)))})")
    healthy = [e for e, (r, d) in oauth_cache.items() if r or (d or 0) > 1]
    if healthy:
        print(f"  Safe window: OAuth still healthy on {len(healthy)}/{len(roster)} account(s). Refreshing now resets the")
        print( "  cookie clock, so cookie-expiry never lands on top of OAuth-expiry. Do it now, not later.")
    elif latched:
        # janitor #82 fix #1: a set denied-latch makes OAuth health UNKNOWN — NOT unhealthy.
        # Firing the URGENT "no healthy OAuth" banner here was the false alarm. And a refresh
        # would NOT clear the latch (that needs `rotator.py clear-keychain-latch` after the
        # human re-grants keychain access); a login is a fresh sign-in that needs no old token.
        print(f"  OAuth health UNKNOWN on {len(latched)}/{len(roster)} account(s): the keychain denied-latch is set, so")
        print("  `security` reads are suppressed. Re-grant keychain access, then run  rotator.py clear-keychain-latch .")
        print("  A login is a fresh human sign-in that needs no old token, so /janitor-refresh-claude-logins still works.")
    elif not health_known:
        # The engine could not report OAuth health (older cached rotator without the
        # oauth-health subcommand, or no cached plugin). Do NOT assert "no healthy
        # OAuth" — that was the C2 false-banner bug. A login is a fresh human sign-in
        # that does not need the old token anyway, so refreshing is always safe.
        print("  OAuth health unknown (rotator engine unavailable) — cannot confirm a safe window, but a")
        print("  login is a fresh human sign-in that does not need the old token, so /janitor-refresh-cc-logins works.")
    else:
        print("  ⚠ URGENT: no account has healthy OAuth right now — refresh immediately. (The login is a fresh")
        print("    human sign-in; it does NOT need the old cookie, so the command still works.)")
    sys.exit(1)
if latched:
    # janitor #82 fix #1: cookies are fine so no refresh is DUE, but a set denied-latch hides
    # OAuth health — say so instead of a bare "all healthy", which here would be misleading.
    print("\n✓ Cookies healthy — nothing urgent. NOTE: keychain denied-latch is set, so OAuth health is UNKNOWN")
    print(f"  on {len(latched)}/{len(roster)} account(s); run  rotator.py clear-keychain-latch  after re-granting keychain access.")
    sys.exit(0)
print("\n✓ All accounts healthy; cookie vs OAuth lifetimes are staggered — nothing to do.")
sys.exit(0)
PY
