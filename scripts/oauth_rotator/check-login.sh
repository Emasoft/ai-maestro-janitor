#!/usr/bin/env bash
# check-login.sh <email> — verify the Chrome profile FILED UNDER <email> now holds
# a LIVE claude.ai session (persistent, survived browser quit). Read-only: reads
# cookie metadata (name/host/expiry) only, NEVER cookie values (those stay encrypted).
# Exit 0 = a session is saved & persisted; non-zero = none saved.
# WHOSE session it is CANNOT be verified offline (janitor#179): cookie values are
# encrypted and no on-disk identity artifact exists — only the capture's /roles
# probe resolves the true owner (and re-files under the ACTUAL account when they
# differ). So the ✓ output claims "a session is saved", never "<email> is logged in".
set -euo pipefail

EMAIL="${1:?usage: check-login.sh <email>}"

# Profiles root via the SHARED engine resolver so open-login.sh / check-login.sh /
# the rotator capture all agree on where chrome-profile-<email> lives. Honour an
# explicit CLAUDE_ROTATOR_PROFILES; else ask the engine's print-profiles-root (accept
# ONLY an absolute path); else the canonical DATA-dir default. Ported into the plugin
# (TRDD-3T4DZWXA): resolve the engine as our IN-PLUGIN SIBLING, never a cache glob, so
# this helper and rotator.py are always the same version.
ROTATOR_PY="${CLAUDE_ROTATOR_PY:-$(cd "$(dirname "$0")" && pwd)/rotator.py}"
PROFILE_ROOT="${CLAUDE_ROTATOR_PROFILES:-}"
if [ -z "$PROFILE_ROOT" ] && [ -n "$ROTATOR_PY" ]; then
  _pr="$(python3 "$ROTATOR_PY" print-profiles-root 2>/dev/null || true)"
  case "$_pr" in /*) PROFILE_ROOT="$_pr" ;; esac
fi
[ -n "$PROFILE_ROOT" ] || PROFILE_ROOT="${CLAUDE_PLUGIN_DATA:-$HOME/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins}/oauth-rotator/profiles"
COOKIES="$PROFILE_ROOT/chrome-profile-$EMAIL/Default/Cookies"

python3 - "$EMAIL" "$COOKIES" <<'PY'
import sqlite3, sys, time, os
email, db = sys.argv[1], sys.argv[2]
if not os.path.exists(db):
    print(f"  ✗ {email}: no cookie store yet (profile never logged in)."); sys.exit(1)
# Chrome expires_utc = microseconds since 1601-01-01.
chrome_now = int((time.time() + 11644473600) * 1_000_000)
try:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT name, expires_utc FROM cookies WHERE host_key LIKE '%claude.ai'"
    ).fetchall()
    con.close()
except sqlite3.Error as e:
    print(f"  ✗ {email}: can't read cookies ({e}). Fully QUIT Chrome (Cmd+Q), then retry.")
    sys.exit(2)
# Persistent (saved) cookies have a future expires_utc; session-only ones (exp==0)
# are dropped when Chrome quits, so they don't count as "saved login".
persistent = [(n, exp) for (n, exp) in rows if exp > chrome_now]
sk = [exp for (n, exp) in persistent if n == "sessionKey"]
# janitor#179: never print "<email>: logged in" — this check proves a session is
# SAVED in the profile filed under <email>, not WHOSE it is (cookie values are
# encrypted; identity resolves only at capture via /roles). A confident ✓-as-<email>
# over a profile signed into another account inverted the operator's advice exactly
# when action was needed.
if sk:
    when = time.strftime("%Y-%m-%d", time.localtime(sk[0] / 1_000_000 - 11644473600))
    print(f"  ✓ {email}: a session is SAVED in this profile — sessionKey valid until ~{when} "
          f"({len(persistent)} persistent claude.ai cookies). Owner unverified offline; "
          f"capture resolves the true account (janitor#179).")
    sys.exit(0)
if len(persistent) >= 5:
    print(f"  ✓ {email}: a session is SAVED — {len(persistent)} persistent claude.ai cookies "
          f"(no cookie literally named sessionKey). Owner unverified offline; "
          f"capture resolves the true account (janitor#179).")
    sys.exit(0)
print(f"  ✗ {email}: not logged in / not persisted "
      f"({len(rows)} claude.ai cookie(s), {len(persistent)} persistent). "
      f"Re-run, log in fully, tick 'stay signed in', then Cmd+Q.")
sys.exit(1)
PY
