---
name: janitor-capture-all-logins
description: Top up EVERY rotator account's OAuth token in one pass, proactively — before any of them expire, not after. Walks the whole roster and re-mints tokens from each account's already-saved claude.ai session (does NOT do the human login itself — run /janitor-refresh-cc-logins first if a session has lapsed). Fires from an `oauth-login-topup` proactive nudge, or on "top up all my logins" / "capture all accounts" / "refresh every rotator token". (Named cc-logins-adjacent — a skill name may not contain the reserved word "claude".)
---

# Janitor capture-all-logins

## Overview

The **proactive, all-accounts** sibling of `/janitor-refresh-cc-logins`
(TRDD-GZXTSJSR P3). Where that skill orchestrates the human LOGIN step (opens
Chrome, the user signs in), this skill assumes every account's claude.ai
session is already saved and just re-runs the OAuth MINT for all of them in
one pass — the fleet-wide "top up before a crisis" flow the periodic
`oauth-login-topup` nudge points at.

Backing script: `$CLAUDE_PLUGIN_ROOT/scripts/capture_all_logins.py`. It lists
the roster via `rotator.py known-emails`, then runs
`slot_capture_browser.py <email>` for each account in sequence, printing
progress per account.

## When to use

- An `[OAUTH-LOGIN-TOPUP]` nudge (desktop notification or heartbeat line) says
  it's time to top up the fleet.
- The user says "top up all my logins" / "capture all accounts" / "refresh
  every rotator token" / "mint tokens for all my accounts".
- After a batch of `/janitor-refresh-cc-logins` re-logins, to mint OAuth for
  all of them in one shot instead of one at a time.

## Instructions

1. **Preflight.** Confirm the backing script exists.

   ```bash
   [ -f "$CLAUDE_PLUGIN_ROOT/scripts/capture_all_logins.py" ] || { echo "missing: capture_all_logins.py"; exit 1; }
   ```

2. **Run the walk.** One call — the script itself prints per-account progress
   and returns non-zero if any account failed:

   ```bash
   env -u CLAUDE_PLUGIN_DATA uv run "$CLAUDE_PLUGIN_ROOT/scripts/capture_all_logins.py"
   ```

3. **Report the outcome.** On full success, tell the user every account is
   topped up. On a partial failure, list the accounts that failed and point
   them at `/janitor-refresh-cc-logins` — a capture only fails per-account
   when that account's saved session has lapsed and needs a fresh human
   login first. On a hard failure (script/engine missing), say exactly what
   is missing and stop; do not retry blindly.

4. **Confirm.** Optionally run the rotator's own status view to double-check
   every slot now holds a refresh-bearing token:

   ```bash
   env -u CLAUDE_PLUGIN_DATA python3 "$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator/rotator.py" list
   ```

## Scope

ONLY re-mints OAuth tokens for accounts that already have a saved claude.ai
session. Does NOT open a login browser and does NOT enter credentials — that
is `/janitor-refresh-cc-logins`'s job. Does NOT change rotator config or
rotate the live account.

## Resources

- `$CLAUDE_PLUGIN_ROOT/scripts/capture_all_logins.py` — the walker (this
  skill's only moving part).
- `$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator/` — the engine (`rotator.py`,
  `slot_capture_browser.py`).
- `/janitor-refresh-cc-logins` — run this FIRST for any account whose saved
  session has lapsed (this skill cannot log a human in).
- The `oauth-rotation-renew-reauth` PROJECT memory page — the ROTATE → RENEW →
  REAUTHENTICATE architecture this skill's walk belongs to.
