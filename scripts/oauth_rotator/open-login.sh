#!/usr/bin/env bash
# open-login.sh <email> — open a clean, REAL Chrome on this account's own
# persistent profile so a human can log into claude.ai once. Blocks until you
# QUIT Chrome (Cmd+Q). Per-account profile = separate cookie jar = no logout.
#
# Clean launch on purpose: no automation flags, no debug port, so Cloudflare +
# Google-2FA treat it as a normal human browser and let you in. The rotator's
# renew step later RE-OPENS this same profile dir (adding --remote-debugging-port)
# and reuses the saved session — it never logs in itself.
set -euo pipefail

EMAIL="${1:?usage: open-login.sh <email>}"

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
PROFILE="$PROFILE_ROOT/chrome-profile-$EMAIL"
mkdir -p "$PROFILE"

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CANARY="/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary"
[ -x "$CANARY" ] && CHROME="$CANARY"
[ -x "$CHROME" ] || { echo "Chrome not found at: $CHROME" >&2; exit 1; }

echo "Opening Chrome for: $EMAIL"
echo "Profile: $PROFILE"
echo "→ Log in as $EMAIL, tick 'stay signed in', then QUIT Chrome (Cmd+Q)."

# Foreground: this blocks until the Chrome process exits (Cmd+Q), so the caller
# can verify the profile immediately afterwards.
exec "$CHROME" \
  --user-data-dir="$PROFILE" \
  --no-first-run \
  --no-default-browser-check \
  --window-size=1280,900 \
  "https://claude.ai/login"
