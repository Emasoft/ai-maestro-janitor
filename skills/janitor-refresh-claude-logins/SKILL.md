---
name: janitor-refresh-claude-logins
description: Refresh the claude.ai login session (cookie) for each rotator account when one nears expiry — the ~monthly human REAUTHENTICATE step the rotator can't automate (claude.ai login needs an OS-level passkey / Google-2FA prompt). Opens Chrome per account (you log in), verifies the session, then mints fresh OAuth tokens via RENEW. Use on an oauth-login-needed / oauth-cookie-reminder nudge, or when "had to log in manually / accounts won't switch / cookie expired". Trigger with /janitor-refresh-claude-logins, "reauth my accounts".
---

# Janitor refresh-claude-logins

## Overview

The interactive multi-account claude.ai login refresher — the **REAUTHENTICATE** leg of the
OAuth rotator, and the ONLY step that needs a human, because the claude.ai login uses a
**passkey / Google-2FA** prompt that is **OS-level — outside any browser**, so no automation
(Playwright, agent-browser, anything) can satisfy it. The user logs in; you orchestrate and
verify. **Never enter credentials or log in for the user — only open the browser and check
results.**

This skill + its helper scripts live IN the plugin (TRDD-3T4DZWXA, completing the
TRDD-f892e109 fold — they were previously a user-scope `/refresh-claude-logins` command). The
rotator ENGINE and these helpers are now always the same plugin version. The architecture is
the `oauth-rotation-renew-reauth` PROJECT memory page (the ROTATE → RENEW → REAUTHENTICATE
3-layer model); this skill is layer 3.

Scripts (in the plugin, beside the rotator engine):

```bash
ROT="$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator"
#   $ROT/rotator.py            — the engine (read-only subcommands + the RENEW tick)
#   $ROT/open-login.sh <email> — open a clean REAL Chrome on the account's profile (blocks until Cmd+Q)
#   $ROT/check-login.sh <email>— verify the profile saved a LIVE session (exit 0 = saved)
#   $ROT/lifetime-status.sh    — cookie-vs-OAuth lifetime table + what's due
```

> Run every rotator invocation with `env -u CLAUDE_PLUGIN_DATA` so the engine resolves the
> JANITOR's data dir via its own guard (a foreign `CLAUDE_PLUGIN_DATA` from another plugin's
> context would otherwise mis-route the state — TRDD-7100178d / TRDD-5EUYV08H). Invoke the engine
> with `python3` (NOT `uv run`) — rotator.py is stdlib-only, so `uv run` would only sync the
> caller's cwd uv-project for no gain; the helper `.sh` drive it the same way (TRDD-3T4DZWXA).

## When to use

- An `oauth-login-needed` or `oauth-cookie-reminder` heartbeat nudge fired (a cookie is
  expiring, or an account needs a fresh human login).
- The user says "refresh my claude logins" / "reauth my accounts" / "I had to log in manually".
- ~Monthly proactive refresh, to stagger cookie-vs-OAuth lifetimes so they never coincide.

## Instructions

1. **Preflight.** Confirm the engine + 3 helpers exist and the rotator resolves a roster. If
   anything is missing, tell the user exactly what and stop.

   ```bash
   ROT="$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator"
   for f in rotator.py open-login.sh check-login.sh lifetime-status.sh; do
     [ -f "$ROT/$f" ] || { echo "missing: $ROT/$f"; exit 1; }
   done
   env -u CLAUDE_PLUGIN_DATA python3 "$ROT/rotator.py" known-emails   # the roster, one email/line
   ```

2. **Show current status first.** Surface `lifetime-status.sh`'s table so the user sees which
   accounts need a refresh and that OAuth is healthy enough to do it safely. (If it says all
   healthy and nothing is due, ask whether they still want to refresh everything anyway.)

   ```bash
   env -u CLAUDE_PLUGIN_DATA bash "$ROT/lifetime-status.sh"
   ```

3. **For EACH account that needs a refresh, in turn:**
   a. Tell the user, as your own message BEFORE launching:
      `▶ Account k/N — a Chrome window will open. Log in as <email>, tick "stay signed in",
       then QUIT Chrome with Cmd+Q (closing just the window is not enough).`
   b. `env -u CLAUDE_PLUGIN_DATA bash "$ROT/open-login.sh" <email>` with a generous Bash
      timeout (it blocks while the user logs in, returns when they Cmd+Q).
   c. `env -u CLAUDE_PLUGIN_DATA bash "$ROT/check-login.sh" <email>` and report ✓/✗. If ✗,
      offer to retry that account (back to 3a) before moving on.

4. **Mint OAuth tokens NOW (RENEW — don't wait for the daemon).** The reauth above only saved
   COOKIES; the OAuth tokens still need minting. Trigger the rotator's renew so each refreshed
   account gets a refresh-bearing slot via the CDP-attach capture (it re-opens the REAL Chrome
   and `connect_over_cdp`-attaches to decrypt the cookies you just saved):

   ```bash
   env -u CLAUDE_PLUGIN_DATA CLAUDE_ROTATOR_AUTO_BOOTSTRAP=1 python3 "$ROT/rotator.py" tick   # _bootstrap_seeded_slots → capture per eligible slot (detached)
   ```

   Captures run DETACHED (a real Chrome window may flash per account, then close). The
   `CLAUDE_ROTATOR_AUTO_BOOTSTRAP=1` above authorizes the capture's visible browser for THIS
   user-initiated run; the unattended daemon keeps auto-bootstrap OFF by default (and caps it
   per slot) so it never opens a surprise window (TRDD-5OJX3SCF). Poll each
   account until its slot holds a refresh token before declaring success
   (`env -u CLAUDE_PLUGIN_DATA python3 "$ROT/rotator.py" list`). If a capture keeps failing,
   re-check `check-login.sh` — the session may not have persisted.

5. **Finish.** Run `lifetime-status.sh` once more to confirm. If every account is ✓ AND its
   slot holds a refresh-bearing token, reassure the user (all refreshed + minted; cookie and
   OAuth lifetimes staggered; the daemon keeps them alive and rotates automatically). If any
   account is still ✗ or its slot stayed empty, list them and what to retry.

## Notes

- Each account has its OWN Chrome profile (separate cookie jar) — you never log out, you just
  log into each account's profile once. Re-run only when a session nears expiry (the monitor /
  the `oauth-cookie-reminder` heartbeat tells you when).
- The opener is a clean, normal Chrome (no automation flags) so Cloudflare + Google-2FA treat
  it as a human browser. The rotator's automation later reuses these saved profiles; it never
  logs in itself. The passkey / 2FA prompt is OS-level — that is WHY this step needs a human
  and cannot be automated.

## Scope

ONLY orchestrates the human claude.ai login refresh + the follow-up OAuth mint for the
rotator's seeded accounts. Does NOT change rotator config, does NOT rotate the live account,
does NOT enter credentials for the user. Toggle daemon-managed rotation with
`/janitor-auto-manage-oauth-on` / `-off`.

## Resources

- `$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator/` — the engine (`rotator.py`, `reauth.py`,
  `slot_capture_browser.py`, …) + the helpers (`open-login.sh`, `check-login.sh`,
  `lifetime-status.sh`).
- `/janitor-auto-manage-oauth-on` / `-off` — toggle daemon-managed rotation.
- The `oauth-rotation-renew-reauth` PROJECT memory page — the ROTATE → RENEW → REAUTHENTICATE
  architecture this skill's layer 3 belongs to.
