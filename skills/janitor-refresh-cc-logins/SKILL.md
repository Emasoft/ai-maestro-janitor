---
name: janitor-refresh-cc-logins
description: Re-stock the rotator with a FULL-OAUTH slot per account via the browser capture. Walks each account's claude.ai login (passkey/2FA, human-only) in a dedicated Chrome, then files the slot with slot_capture_browser.py — a ~8h access token the daemon keepalive renews on its own. INTERACTIVE — the login needs a passkey prompt, so it PAUSES for the user; never select it in a cron or headless context. Use on an oauth-login-needed / oauth-cookie-reminder nudge, when a slot's refresh is dead, or when "had to rotate manually / accounts won't switch / cookie expired". Trigger with /janitor-refresh-cc-logins, "reauth my accounts".
---

# Janitor refresh-cc-logins

## Overview

The interactive multi-account credential re-stocker — the **REAUTHENTICATE** leg of the OAuth
rotator. The login step needs a human, for a hard reason: the claude.ai sign-in uses a
**passkey / Google-2FA** prompt that is **OS-level — outside any browser**. The user logs in;
you orchestrate, then run the capture and verify it. **Never enter credentials or log in for
the user — only open the browser and check results.**

What the rotator ends up holding is a **FULL-OAUTH slot with a refreshToken** per account: an
access token of roughly 8 hours that the daemon's keepalive renews by itself. After the
capture, the rotator rotates AND renews unattended; this skill is only the re-seeding step
when a slot goes credential-dead or an account was never seeded. (This replaced, per owner
ruling 2026-09-24, the older one-year static-key flow: those keys do not work — the
owner-ratified procedure lives in the PROJECT memory page below, atom ATOM-VH28-30GK.)

This skill + its helper scripts live IN the plugin (TRDD-3T4DZWXA, completing the
TRDD-f892e109 fold — they were previously a user-scope `/refresh-claude-logins` command). The
rotator ENGINE and these helpers are now always the same plugin version. The architecture is
the `oauth-rotation-renew-reauth` PROJECT memory page (the ROTATE → RENEW → REAUTHENTICATE
3-layer model); this skill is layer 3.

Scripts (in the plugin, beside the rotator engine):

```bash
ROT="$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator"
#   $ROT/rotator.py               — the engine (read-only subcommands + the RENEW tick)
#   $ROT/open-login.sh <email>    — open a clean REAL Chrome on the account's profile (blocks until Cmd+Q)
#   $ROT/check-login.sh <email>   — verify the profile saved a LIVE session (exit 0 = saved)
#   $ROT/slot_capture_browser.py <email> — file the FULL-OAUTH slot from that profile
#   $ROT/lifetime-status.sh       — cookie-vs-OAuth lifetime table + what's due
```

> Run every rotator invocation with `env -u CLAUDE_PLUGIN_DATA` so the engine resolves the
> JANITOR's data dir via its own guard (a foreign `CLAUDE_PLUGIN_DATA` from another plugin's
> context would otherwise mis-route the state — TRDD-7100178d / TRDD-5EUYV08H). Invoke the engine
> with `python3` (NOT `uv run`) — rotator.py is stdlib-only, so `uv run` would only sync the
> caller's cwd uv-project for no gain; the helper `.sh` drive it the same way (TRDD-3T4DZWXA).
> The capture is the one exception — it needs Playwright, so the ratified line uses
> `uv run --no-project --with playwright python` (step 4).

## When to use

- An `oauth-login-needed` or `oauth-cookie-reminder` heartbeat nudge fired (a cookie is
  expiring, or an account needs a fresh human login).
- The user says "refresh my claude logins" / "reauth my accounts" / "I had to log in manually".
- ~Monthly proactive refresh, to stagger cookie-vs-OAuth lifetimes so they never coincide.

## Instructions

1. **Preflight.** Confirm the engine + 4 helpers exist and the rotator resolves a roster. If
   anything is missing, tell the user exactly what and stop.

   ```bash
   ROT="$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator"
   for f in rotator.py open-login.sh check-login.sh slot_capture_browser.py lifetime-status.sh; do
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

3. **For EACH account that needs a refresh — alternates first, the LIVE account LAST** (why:
   step 4c). In turn:
   a. Tell the user, as your own message BEFORE launching:
      `▶ Account k/N — a Chrome window will open. Log in as <email>, tick "stay signed in",
       then QUIT Chrome with Cmd+Q (closing just the window is not enough).`
   b. `env -u CLAUDE_PLUGIN_DATA bash "$ROT/open-login.sh" <email>` with a generous Bash
      timeout (it blocks while the user logs in, returns when they Cmd+Q). This step has NO
      Authorize button — it only saves the claude.ai session into that profile.
   c. `env -u CLAUDE_PLUGIN_DATA bash "$ROT/check-login.sh" <email>` and report ✓/✗. If ✗,
      offer to retry that account (back to 3a) before moving on. Exit 0 means A session is
      saved; it cannot tell WHOSE — step 4b is what catches the wrong one.

4. **File the FULL-OAUTH slot.** Auto-bootstrap runs by default (TRDD-0SU2C2IM): the rotator
   launches this capture itself for a credential-dead slot, skips the live account, and
   launches nothing when the live account is unknown. Setting `CLAUDE_ROTATOR_AUTO_BOOTSTRAP`
   to `0`, `false`, `no` or `off` disables it. A capture whose Chrome profile is signed in to a
   different account is refused before Authorize. The automatic path is best-effort — run
   this step by hand whenever a slot is still credential-dead: the claude.ai web session
   expired (needs your passkey/2FA), the slot is the live account, the automatic attempts ran
   out (per-slot launch cap) or were refused, or auto-bootstrap is disabled.

   a. Run the capture for the account you just logged in (owner-ratified verbatim line):

      ```bash
      env -u CLAUDE_PLUGIN_DATA uv run --no-project --with playwright python \
        "$ROT/slot_capture_browser.py" <email>
      ```

      It reopens that profile, clicks Authorize itself, and files a slot WITH a refreshToken.

   b. **Verify the email, not just success.** The final line must read
      `OK: filed FULL-OAUTH slot for <email>` naming THE SAME email — a profile holding
      another account's session re-files under THAT account (janitor#179), and nothing
      downstream can detect the swap. Also confirm
      `env -u CLAUDE_PLUGIN_DATA python3 "$ROT/rotator.py" list` shows a fresh `captured=`.

   c. **Redact any output you show.** A capture mints a new OAuth grant, and if the server
      evicts older grants a capture on the LIVE account can break the running session's own
      refresh — that is why step 3 captures alternates first and live last. When showing
      capture output, REDACT (`sed` on `code=`, `state=`, `access_token=`, `refresh_token=`,
      `sk-ant-…`). Never DROP lines with `grep -v` — that hides the
      `FAILED: token exchange HTTP 403` reason line.

5. **Finish.** Run `lifetime-status.sh` once more to confirm. Success is every account holding
   a FULL-OAUTH slot with a fresh `captured=` date; on the next tick `rotator.log` shows
   `auto: live <email> 5h=… 7d=…` instead of "no usable slot twin" — probing works, and the
   keepalive renews each slot from there. Then tell the user plainly: the daemon's remaining
   job is rotate + renew, hands-free, until a slot next goes credential-dead (the heartbeat
   nudge says when). List any account whose slot stayed empty and what to retry.

## Notes

- Each account has its OWN Chrome profile (separate cookie jar) — you never log out, you just
  log into each account's profile once. Re-run only when a session nears expiry (the monitor /
  the `oauth-cookie-reminder` heartbeat tells you when).
- The opener is a clean, normal Chrome (no automation flags) so Cloudflare + Google-2FA treat
  it as a human browser; it never logs in itself. The passkey / 2FA prompt is OS-level — that
  is WHY the login needs a human and cannot be automated.
- The capture (step 4a) is the only non-stdlib invocation: Playwright drives the Authorize
  click. Everything else is stdlib `python3`.

## Naming

Called `cc-logins`, not `claude-logins`: a skill name may not contain the reserved word
"claude". Moved here from the frontmatter `description:`, which is capped at 200 tokens and
is for stating WHEN to invoke the skill — not for maintainer notes.

## Scope

ONLY orchestrates the human claude.ai login refresh and the browser capture that files each
FULL-OAUTH slot. Does NOT change rotator config, does NOT rotate to a DIFFERENT account, does
NOT enter credentials for the user, and does NOT run unattended (the login needs the human).
Rotate deliberately with `/janitor-rotate-account-to`; toggle daemon-managed rotation with
`/janitor-auto-manage-oauth-on` / `-off`.

## Resources

- `$CLAUDE_PLUGIN_ROOT/scripts/oauth_rotator/` — the engine (`rotator.py`, `reauth.py`,
  `slot_capture_browser.py`, …) + the helpers (`open-login.sh`, `check-login.sh`,
  `lifetime-status.sh`).
- `/janitor-auto-manage-oauth-on` / `-off` — toggle daemon-managed rotation.
- `/janitor-capture-all-logins` — the proactive all-accounts sibling (mints from already-saved
  sessions, no human login).
- The `oauth-rotation-renew-reauth` PROJECT memory page — the ROTATE → RENEW → REAUTHENTICATE
  architecture this skill's layer 3 belongs to, and the owner-ratified renew procedure
  (ATOM-VH28-30GK) this skill implements.
